import assert from 'node:assert/strict';
import test from 'node:test';

import { GitHubApiError } from '../src/errors.js';
import {
  labels,
  normalizeApiBaseUrl,
  normalizePrivateKey,
  repositoryPath,
  retryDelayMilliseconds,
} from '../src/validation.js';

test('restricts API base URL to HTTPS or loopback HTTP', () => {
  assert.equal(normalizeApiBaseUrl('https://api.github.com').href, 'https://api.github.com/');
  assert.equal(normalizeApiBaseUrl('http://127.0.0.1:8000').href, 'http://127.0.0.1:8000/');
  assert.throws(() => normalizeApiBaseUrl('http://example.com'), GitHubApiError);
  assert.throws(() => normalizeApiBaseUrl('https://user:pass@example.com'), GitHubApiError);
});

test('validates repository paths and labels', () => {
  assert.equal(repositoryPath('/src/example.ts'), 'src/example.ts');
  assert.throws(() => repositoryPath('../secret'), GitHubApiError);
  assert.deepEqual(labels(['ready', 'ready', 'needs-review']), ['ready', 'needs-review']);
  assert.throws(() => labels([]), GitHubApiError);
});

test('normalizes PEM and base64 PEM private keys', () => {
  const pem = '-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----';
  assert.equal(normalizePrivateKey(pem), pem);
  assert.equal(normalizePrivateKey(Buffer.from(pem).toString('base64')), pem);
});

test('caps retry waits even when rate-limit reset is far away', () => {
  const headers = new Headers({
    'x-ratelimit-remaining': '0',
    'x-ratelimit-reset': String(Math.floor(Date.parse('2026-08-02T00:00:00Z') / 1000)),
  });
  assert.equal(
    retryDelayMilliseconds(headers, new Date('2026-08-01T00:00:00Z'), 250, 5_000),
    5_000,
  );
});
