import assert from 'node:assert/strict';
import { generateKeyPairSync, verify } from 'node:crypto';
import test from 'node:test';

import {
  createGitHubAppJwt,
  GitHubAppTokenProvider,
  PatTokenProvider,
} from '../src/auth.js';
import { GitHubApiError } from '../src/errors.js';

function decodeJson(segment: string): Record<string, unknown> {
  const padding = '='.repeat((4 - (segment.length % 4)) % 4);
  const value = Buffer.from(segment.replace(/-/g, '+').replace(/_/g, '/') + padding, 'base64').toString(
    'utf8',
  );
  return JSON.parse(value) as Record<string, unknown>;
}

test('creates a verifiable RS256 GitHub App JWT with bounded lifetime', () => {
  const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const now = new Date('2026-08-01T00:00:00.000Z');
  const jwt = createGitHubAppJwt(
    '12345',
    privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
    now,
  );
  const [header, payload, signature] = jwt.split('.');
  assert.ok(header && payload && signature);
  assert.deepEqual(decodeJson(header), { alg: 'RS256', typ: 'JWT' });
  const payloadObject = decodeJson(payload);
  assert.equal(payloadObject.iss, '12345');
  assert.equal(payloadObject.iat, Math.floor(now.getTime() / 1000) - 60);
  assert.equal(payloadObject.exp, Math.floor(now.getTime() / 1000) + 540);
  const signatureBytes = Buffer.from(
    signature.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (signature.length % 4)) % 4),
    'base64',
  );
  assert.equal(
    verify(
      'RSA-SHA256',
      Buffer.from(`${header}.${payload}`),
      publicKey,
      signatureBytes,
    ),
    true,
  );
});

test('GitHub App provider accepts variable-length installation tokens and caches by intent', async () => {
  const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  let calls = 0;
  const requests: Array<{ url: string; body: string }> = [];
  const provider = new GitHubAppTokenProvider(
    {
      baseUrl: 'http://127.0.0.1:8123',
      apiVersion: '2026-03-10',
      appId: '12345',
      installationId: '67890',
      privateKey: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
      timeoutMs: 5_000,
      fetchImpl: (async (input, init) => {
        calls += 1;
        requests.push({ url: String(input), body: String(init?.body ?? '') });
        return new Response(
          JSON.stringify({
            token: `ghs_12345_${'x'.repeat(90)}_${calls}`,
            expires_at: '2026-08-01T01:00:00.000Z',
          }),
          { status: 201, headers: { 'content-type': 'application/json' } },
        );
      }) as typeof fetch,
      now: () => new Date('2026-08-01T00:00:00.000Z'),
    },
    true,
  );

  const readOne = await provider.token('read');
  const readTwo = await provider.token('read');
  const writeOne = await provider.token('write');
  assert.equal(readOne, readTwo);
  assert.notEqual(readOne, writeOne);
  assert.equal(calls, 2);
  assert.match(requests[0]?.body ?? '', /"pull_requests":"read"/);
  assert.match(requests[1]?.body ?? '', /"pull_requests":"write"/);
});

test('PAT provider separates reads from writes and honors the global write gate', async () => {
  const disabled = new PatTokenProvider('read-token', 'write-token', false);
  assert.equal(await disabled.token('read'), 'read-token');
  await assert.rejects(() => disabled.token('write'), (error: unknown) => {
    return error instanceof GitHubApiError && error.code === 'writes_disabled';
  });

  const enabled = new PatTokenProvider('read-token', 'write-token', true);
  assert.equal(await enabled.token('read'), 'read-token');
  assert.equal(await enabled.token('write'), 'write-token');
});
