import assert from 'node:assert/strict';
import test from 'node:test';

import { ArchimedesPublicClient } from '../src/client.js';
import { ArchimedesApiError } from '../src/errors.js';
import { sendJson, startTestServer } from './helpers.js';

const ASSET_ID = '46d1682f-6ceb-4288-97ae-8a05a4ab9c86';
const BOUNTY_ID = '5586f0c8-cde1-416c-ac28-d85bc6a264f0';
const FIXED_NOW = new Date('2026-07-31T00:00:00.000Z');

test('searches and fetches public resources using GET only', async () => {
  const observations: Array<{ method: string | undefined; accept: string | undefined }> = [];
  const server = await startTestServer((request, response) => {
    observations.push({ method: request.method, accept: request.headers.accept });
    const url = new URL(request.url ?? '/', 'http://localhost');
    if (url.pathname === '/api/public/assets') {
      sendJson(response, {
        total: 3,
        items: [
          { id: ASSET_ID, title: 'Python stress calculator', asset_type: 'CODE' },
          { id: '312e3c99-f858-44e7-ba2c-fcaf408825a8', title: 'Rust bridge', asset_type: 'CODE' },
          { id: 'aa632521-f830-4adf-9828-7c6079e06a83', title: 'Python report', asset_type: 'DOCUMENT' },
        ],
      });
      return;
    }
    if (url.pathname === `/api/public/assets/${ASSET_ID}`) {
      sendJson(response, { id: ASSET_ID, title: 'Python stress calculator' });
      return;
    }
    if (url.pathname === '/api/public/bounties') {
      assert.equal(url.searchParams.get('status'), 'open');
      sendJson(response, {
        total: 2,
        items: [
          {
            id: BOUNTY_ID,
            display_id: 'MSN-00013',
            title: 'Develop an MCP Server',
            category: 'software',
            is_funded: true,
            escrow_status: 'locked',
          },
          {
            id: '11111111-1111-4111-8111-111111111111',
            title: 'Unfunded MCP idea',
            category: 'software',
            is_funded: false,
            escrow_status: 'unfunded',
          },
        ],
      });
      return;
    }
    if (url.pathname === `/api/public/bounties/${BOUNTY_ID}`) {
      sendJson(response, { id: BOUNTY_ID, display_id: 'MSN-00013', acceptance_tests: [] });
      return;
    }
    sendJson(response, { error: 'not found' }, 404);
  });

  try {
    const client = new ArchimedesPublicClient({
      baseUrl: server.baseUrl,
      maxRetries: 0,
      now: () => FIXED_NOW,
    });
    const assets = await client.searchAssets({ query: 'Python', asset_type: 'CODE', limit: 10 });
    assert.equal(assets.returned, 1);
    assert.equal(assets.total, 3);
    assert.equal((assets.items[0] as { id: string }).id, ASSET_ID);
    assert.equal((await client.getAsset(ASSET_ID)).id, ASSET_ID);

    const bounties = await client.searchBounties({ query: 'MCP', category: 'software' });
    assert.equal(bounties.returned, 1);
    assert.equal((bounties.items[0] as { id: string }).id, BOUNTY_ID);
    assert.equal(bounties.query.funded_only, true);
    assert.equal((await client.getBounty(BOUNTY_ID)).id, BOUNTY_ID);

    assert.equal(observations.length, 4);
    assert.ok(observations.every((item) => item.method === 'GET'));
    assert.ok(observations.every((item) => item.accept === 'application/json'));
  } finally {
    await server.close();
  }
});

test('retries a bounded HTTP 429 and honors Retry-After', async () => {
  let attempts = 0;
  const sleeps: number[] = [];
  const server = await startTestServer((_request, response) => {
    attempts += 1;
    if (attempts === 1) {
      response.statusCode = 429;
      response.setHeader('retry-after', '0');
      response.setHeader('x-ratelimit-remaining', '0');
      response.end();
      return;
    }
    sendJson(response, { items: [], total: 0 });
  });
  try {
    const client = new ArchimedesPublicClient({
      baseUrl: server.baseUrl,
      maxRetries: 1,
      sleep: async (milliseconds) => {
        sleeps.push(milliseconds);
      },
    });
    assert.equal((await client.searchAssets()).returned, 0);
    assert.equal(attempts, 2);
    assert.deepEqual(sleeps, [0]);
  } finally {
    await server.close();
  }
});

test('rejects traversal before making a request', async () => {
  let requests = 0;
  const server = await startTestServer((_request, response) => {
    requests += 1;
    sendJson(response, {});
  });
  try {
    const client = new ArchimedesPublicClient({ baseUrl: server.baseUrl, maxRetries: 0 });
    await assert.rejects(() => client.getAsset('../../etc/passwd'), (error: unknown) => {
      assert.ok(error instanceof ArchimedesApiError);
      assert.equal(error.code, 'invalid_identifier');
      return true;
    });
    assert.equal(requests, 0);
  } finally {
    await server.close();
  }
});

test('rejects oversized, invalid JSON, and redirect responses', async (t) => {
  await t.test('oversized body', async () => {
    const server = await startTestServer((_request, response) => {
      const body = JSON.stringify({ items: ['x'.repeat(2_000)] });
      response.statusCode = 200;
      response.setHeader('content-length', String(Buffer.byteLength(body)));
      response.end(body);
    });
    try {
      const client = new ArchimedesPublicClient({
        baseUrl: server.baseUrl,
        maxRetries: 0,
        maxResponseBytes: 1_024,
      });
      await assert.rejects(() => client.searchAssets(), (error: unknown) => {
        assert.ok(error instanceof ArchimedesApiError);
        assert.equal(error.code, 'response_too_large');
        return true;
      });
    } finally {
      await server.close();
    }
  });

  await t.test('invalid JSON', async () => {
    const server = await startTestServer((_request, response) => {
      response.end('{not-json');
    });
    try {
      const client = new ArchimedesPublicClient({ baseUrl: server.baseUrl, maxRetries: 0 });
      await assert.rejects(() => client.searchAssets(), (error: unknown) => {
        assert.ok(error instanceof ArchimedesApiError);
        assert.equal(error.code, 'invalid_response');
        return true;
      });
    } finally {
      await server.close();
    }
  });

  await t.test('redirect', async () => {
    const server = await startTestServer((_request, response) => {
      response.statusCode = 302;
      response.setHeader('location', 'https://example.com/');
      response.end();
    });
    try {
      const client = new ArchimedesPublicClient({ baseUrl: server.baseUrl, maxRetries: 0 });
      await assert.rejects(() => client.searchAssets(), (error: unknown) => {
        assert.ok(error instanceof ArchimedesApiError);
        assert.equal(error.code, 'network_error');
        return true;
      });
    } finally {
      await server.close();
    }
  });
});
