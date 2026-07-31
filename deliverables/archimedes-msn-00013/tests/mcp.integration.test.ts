import assert from 'node:assert/strict';
import path from 'node:path';
import process from 'node:process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

import { sendJson, startTestServer } from './helpers.js';

const ASSET_ID = '46d1682f-6ceb-4288-97ae-8a05a4ab9c86';
const BOUNTY_ID = '5586f0c8-cde1-416c-ac28-d85bc6a264f0';
const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function stringEnvironment(): Record<string, string> {
  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) {
      output[key] = value;
    }
  }
  return output;
}

test('registers exactly four read-only tools and serves them over stdio', async () => {
  const api = await startTestServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    if (url.pathname === '/api/public/assets') {
      sendJson(response, {
        total: 1,
        items: [{ id: ASSET_ID, title: 'Python Engineering Model', asset_type: 'CODE' }],
      });
      return;
    }
    if (url.pathname === `/api/public/assets/${ASSET_ID}`) {
      sendJson(response, { id: ASSET_ID, title: 'Python Engineering Model' });
      return;
    }
    if (url.pathname === '/api/public/bounties') {
      sendJson(response, {
        total: 1,
        items: [
          {
            id: BOUNTY_ID,
            display_id: 'MSN-00013',
            title: 'Develop an MCP Server for Archimedes Market',
            is_funded: true,
            escrow_status: 'locked',
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

  const transport = new StdioClientTransport({
    command: process.execPath,
    args: ['--import', 'tsx', 'src/index.ts'],
    cwd: PROJECT_ROOT,
    stderr: 'pipe',
    env: {
      ...stringEnvironment(),
      ARCHIMEDES_BASE_URL: api.baseUrl,
      ARCHIMEDES_MAX_RETRIES: '0',
      ARCHIMEDES_TIMEOUT_MS: '5000',
    },
  });
  let stderr = '';
  transport.stderr?.on('data', (chunk) => {
    stderr += String(chunk);
  });

  const client = new Client({ name: 'archimedes-market-mcp-test', version: '1.0.0' });
  try {
    await client.connect(transport);
    const listed = await client.listTools();
    assert.deepEqual(
      listed.tools.map((tool) => tool.name).sort(),
      ['get_asset', 'get_bounty', 'search_assets', 'search_bounties'],
    );
    for (const tool of listed.tools) {
      assert.deepEqual(tool.annotations, {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      });
    }

    const assets = await client.callTool({
      name: 'search_assets',
      arguments: { query: 'Python', asset_type: 'CODE' },
    });
    assert.equal((assets.structuredContent as { returned: number }).returned, 1);

    const asset = await client.callTool({ name: 'get_asset', arguments: { asset_id: ASSET_ID } });
    assert.equal((asset.structuredContent as { id: string }).id, ASSET_ID);

    const bounties = await client.callTool({ name: 'search_bounties', arguments: { query: 'MCP' } });
    assert.equal((bounties.structuredContent as { returned: number }).returned, 1);

    const bounty = await client.callTool({ name: 'get_bounty', arguments: { bounty_id: BOUNTY_ID } });
    assert.equal((bounty.structuredContent as { id: string }).id, BOUNTY_ID);
  } finally {
    await client.close().catch(() => undefined);
    await api.close();
  }

  assert.doesNotMatch(stderr, /failed to start/i);
});
