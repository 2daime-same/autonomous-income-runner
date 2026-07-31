import assert from 'node:assert/strict';
import test from 'node:test';

import { ArchimedesPublicClient } from '../src/client.js';
import { ArchimedesApiError } from '../src/errors.js';
import { assetHtml, sendJson, sendText, sitemapXml, startTestServer } from './helpers.js';

const ASSET_ID = '46d1682f-6ceb-4288-97ae-8a05a4ab9c86';
const SECOND_ASSET_ID = '312e3c99-f858-44e7-ba2c-fcaf408825a8';
const THIRD_ASSET_ID = 'aa632521-f830-4adf-9828-7c6079e06a83';
const BOUNTY_ID = '5586f0c8-cde1-416c-ac28-d85bc6a264f0';
const FIXED_NOW = new Date('2026-07-31T00:00:00.000Z');

test('searches static public assets and official public bounties using GET only', async () => {
  const observations: Array<{ method: string | undefined; path: string; accept: string | undefined }> = [];
  let baseUrl = '';
  const server = await startTestServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    observations.push({ method: request.method, path: url.pathname, accept: request.headers.accept });
    if (url.pathname === '/sitemap.xml') {
      sendText(response, sitemapXml(baseUrl, [ASSET_ID, SECOND_ASSET_ID, THIRD_ASSET_ID]), 'application/xml');
      return;
    }
    if (url.pathname === `/assets/${ASSET_ID}`) {
      sendText(
        response,
        assetHtml(baseUrl, {
          id: ASSET_ID,
          title: 'Python stress calculator',
          description: 'Engineering calculations in Python',
          assetType: 'CODE',
        }),
        'text/html',
      );
      return;
    }
    if (url.pathname === `/assets/${SECOND_ASSET_ID}`) {
      sendText(
        response,
        assetHtml(baseUrl, {
          id: SECOND_ASSET_ID,
          title: 'Rust bridge',
          description: 'Engineering calculations in Rust',
          assetType: 'CODE',
        }),
        'text/html',
      );
      return;
    }
    if (url.pathname === `/assets/${THIRD_ASSET_ID}`) {
      sendText(
        response,
        assetHtml(baseUrl, {
          id: THIRD_ASSET_ID,
          title: 'Python report',
          description: 'A written Python engineering report',
          assetType: 'DOCUMENT',
        }),
        'text/html',
      );
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
  baseUrl = server.baseUrl;

  try {
    const client = new ArchimedesPublicClient({
      baseUrl,
      maxRetries: 0,
      now: () => FIXED_NOW,
      assetScanConcurrency: 2,
    });
    const assets = await client.searchAssets({ query: 'Python', asset_type: 'CODE', limit: 10 });
    assert.equal(assets.returned, 1);
    assert.equal(assets.total, 1);
    assert.equal((assets.items[0] as { id: string }).id, ASSET_ID);
    assert.equal((assets.items[0] as { metadata_source: string }).metadata_source, 'public static schema.org Product JSON-LD');
    assert.equal((await client.getAsset(ASSET_ID)).id, ASSET_ID);

    const bounties = await client.searchBounties({ query: 'MCP', category: 'software' });
    assert.equal(bounties.returned, 1);
    assert.equal((bounties.items[0] as { id: string }).id, BOUNTY_ID);
    assert.equal(bounties.query.funded_only, true);
    assert.equal((await client.getBounty(BOUNTY_ID)).id, BOUNTY_ID);

    assert.equal(observations.length, 6);
    assert.ok(observations.every((item) => item.method === 'GET'));
    assert.ok(observations.every((item) => item.accept !== undefined));
    assert.ok(observations.every((item) => !item.path.includes('increment_view_count')));
    assert.ok(observations.every((item) => !item.path.startsWith('/api/public/assets')));
  } finally {
    await server.close();
  }
});

test('fetches only the requested asset page for an unfiltered page', async () => {
  let baseUrl = '';
  const paths: string[] = [];
  const server = await startTestServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    paths.push(url.pathname);
    if (url.pathname === '/sitemap.xml') {
      sendText(response, sitemapXml(baseUrl, [ASSET_ID, SECOND_ASSET_ID, THIRD_ASSET_ID]), 'application/xml');
      return;
    }
    if (url.pathname === `/assets/${SECOND_ASSET_ID}`) {
      sendText(response, assetHtml(baseUrl, { id: SECOND_ASSET_ID, title: 'Second asset' }), 'text/html');
      return;
    }
    sendJson(response, { error: 'unexpected request' }, 500);
  });
  baseUrl = server.baseUrl;
  try {
    const client = new ArchimedesPublicClient({ baseUrl, maxRetries: 0 });
    const result = await client.searchAssets({ limit: 1, offset: 1 });
    assert.equal(result.total, 3);
    assert.equal(result.returned, 1);
    assert.equal((result.items[0] as { id: string }).id, SECOND_ASSET_ID);
    assert.deepEqual(paths, ['/sitemap.xml', `/assets/${SECOND_ASSET_ID}`]);
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
    assert.equal((await client.searchBounties({ funded_only: false })).returned, 0);
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
      await assert.rejects(() => client.searchBounties(), (error: unknown) => {
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
      await assert.rejects(() => client.searchBounties(), (error: unknown) => {
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
      await assert.rejects(() => client.searchBounties(), (error: unknown) => {
        assert.ok(error instanceof ArchimedesApiError);
        assert.equal(error.code, 'network_error');
        return true;
      });
    } finally {
      await server.close();
    }
  });
});
