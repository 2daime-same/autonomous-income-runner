import assert from 'node:assert/strict';
import test from 'node:test';

import { GitHubApiError } from '../src/errors.js';
import { GitHubHttpClient } from '../src/http.js';
import { StaticTokenProvider, sendJson, startTestServer } from './helpers.js';

test('retries rate-limited GET once but never retries POST', async () => {
  let getCalls = 0;
  let postCalls = 0;
  const api = await startTestServer((request, response) => {
    if (request.method === 'GET') {
      getCalls += 1;
      if (getCalls === 1) {
        sendJson(response, { message: 'rate limit' }, 429, { 'retry-after': '0' });
      } else {
        sendJson(response, []);
      }
      return;
    }
    postCalls += 1;
    sendJson(response, { message: 'temporary failure' }, 503);
  });
  const sleeps: number[] = [];
  const client = new GitHubHttpClient({
    baseUrl: api.baseUrl,
    maxRetries: 1,
    maxRetryDelayMs: 10,
    tokenProvider: new StaticTokenProvider(),
    sleep: async (milliseconds) => {
      sleeps.push(milliseconds);
    },
  });
  try {
    const result = await client.getJson('repos/example/project/pulls');
    assert.deepEqual(result.data, []);
    assert.equal(getCalls, 2);
    assert.equal(sleeps.length, 0);

    await assert.rejects(
      () => client.postJson('repos/example/project/issues/1/labels', { labels: ['ready'] }),
      (error: unknown) => error instanceof GitHubApiError && error.status === 503,
    );
    assert.equal(postCalls, 1);
  } finally {
    await api.close();
  }
});

test('follows only same-origin GET redirects', async () => {
  const api = await startTestServer((request, response) => {
    if (request.url?.startsWith('/repos/example/project/pulls?')) {
      response.statusCode = 302;
      response.setHeader('location', '/repos/example/project/pulls/1');
      response.end();
      return;
    }
    sendJson(response, { number: 1 });
  });
  const client = new GitHubHttpClient({ baseUrl: api.baseUrl, maxRetries: 0 });
  try {
    const result = await client.getJson('repos/example/project/pulls', { state: 'open' });
    assert.equal((result.data as { number: number }).number, 1);
  } finally {
    await api.close();
  }

  const refusing = new GitHubHttpClient({
    baseUrl: 'http://127.0.0.1:8123',
    maxRetries: 0,
    fetchImpl: (async () =>
      new Response('', { status: 302, headers: { location: 'https://evil.example/path' } })) as typeof fetch,
  });
  await assert.rejects(
    () => refusing.getJson('repos/example/project/pulls'),
    (error: unknown) => error instanceof GitHubApiError && error.code === 'redirect_refused',
  );
});

test('bounds response size and redacts arbitrary upstream HTML', async () => {
  const large = new GitHubHttpClient({
    baseUrl: 'http://127.0.0.1:8123',
    maxResponseBytes: 16_384,
    maxRetries: 0,
    fetchImpl: (async () => new Response('x'.repeat(20_000), { status: 200 })) as typeof fetch,
  });
  await assert.rejects(
    () => large.getText('repos/example/project/pulls/1'),
    (error: unknown) => error instanceof GitHubApiError && error.code === 'response_too_large',
  );

  const html = new GitHubHttpClient({
    baseUrl: 'http://127.0.0.1:8123',
    maxRetries: 0,
    fetchImpl: (async () =>
      new Response('<html>secret internal stack</html>', { status: 500 })) as typeof fetch,
  });
  await assert.rejects(() => html.getJson('repos/example/project/pulls'), (error: unknown) => {
    assert.ok(error instanceof GitHubApiError);
    assert.doesNotMatch(error.message, /secret|stack/i);
    return true;
  });
});

test('rejects API paths outside supported pull and issue endpoints', async () => {
  const client = new GitHubHttpClient({ baseUrl: 'http://127.0.0.1:8123', maxRetries: 0 });
  await assert.rejects(
    () => client.getJson('user/emails'),
    (error: unknown) => error instanceof GitHubApiError && error.code === 'invalid_path',
  );
});
