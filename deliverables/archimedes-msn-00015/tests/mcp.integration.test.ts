import assert from 'node:assert/strict';
import path from 'node:path';
import process from 'node:process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

import { SAMPLE_PATCH, sendJson, startTestServer } from './helpers.js';

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

test('registers eight tools and two opt-in review prompts over stdio', async () => {
  const api = await startTestServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    if (url.pathname === '/repos/example/project/pulls') {
      sendJson(response, [
        {
          number: 7,
          title: 'Example PR',
          state: 'open',
          draft: false,
          user: { login: 'contributor' },
          head: { ref: 'feature', sha: 'abc123', repo: { full_name: 'example/project' } },
          base: { ref: 'main', sha: 'def456', repo: { full_name: 'example/project' } },
          labels: [],
        },
      ]);
      return;
    }
    if (url.pathname === '/repos/example/project/pulls/7') {
      sendJson(response, {
        number: 7,
        title: 'Example PR',
        state: 'open',
        draft: false,
        user: { login: 'contributor' },
        head: { ref: 'feature', sha: 'abc123', repo: { full_name: 'example/project' } },
        base: { ref: 'main', sha: 'def456', repo: { full_name: 'example/project' } },
        labels: [],
        mergeable: true,
      });
      return;
    }
    if (url.pathname === '/repos/example/project/pulls/7/files') {
      sendJson(response, [
        {
          filename: 'src/example.ts',
          status: 'modified',
          additions: 2,
          deletions: 1,
          changes: 3,
          patch: SAMPLE_PATCH,
        },
      ]);
      return;
    }
    if (
      url.pathname === '/repos/example/project/issues/7/comments' ||
      url.pathname === '/repos/example/project/pulls/7/reviews' ||
      url.pathname === '/repos/example/project/pulls/7/comments'
    ) {
      sendJson(response, []);
      return;
    }
    sendJson(response, { message: 'not found' }, 404);
  });

  const transport = new StdioClientTransport({
    command: process.execPath,
    args: ['--import', 'tsx', 'src/index.ts'],
    cwd: PROJECT_ROOT,
    stderr: 'pipe',
    env: {
      ...stringEnvironment(),
      GITHUB_API_BASE_URL: api.baseUrl,
      GITHUB_AUTH_MODE: 'none',
      GITHUB_ALLOW_WRITES: 'false',
      GITHUB_MAX_RETRIES: '0',
      GITHUB_TIMEOUT_MS: '5000',
    },
  });
  let stderr = '';
  transport.stderr?.on('data', (chunk) => {
    stderr += String(chunk);
  });

  const client = new Client({ name: 'archimedes-github-pr-mcp-test', version: '1.0.0' });
  try {
    await client.connect(transport);
    const listed = await client.listTools();
    assert.deepEqual(
      listed.tools.map((tool) => tool.name).sort(),
      [
        'add_labels',
        'get_pr',
        'get_pr_diff',
        'list_pr_comments',
        'list_prs',
        'post_review_comment',
        'request_changes',
        'submit_review',
      ],
    );
    for (const tool of listed.tools.filter((entry) =>
      ['list_prs', 'get_pr', 'get_pr_diff', 'list_pr_comments'].includes(entry.name),
    )) {
      assert.equal(tool.annotations?.readOnlyHint, true);
      assert.equal(tool.annotations?.idempotentHint, true);
    }
    for (const tool of listed.tools.filter((entry) =>
      ['post_review_comment', 'submit_review', 'add_labels', 'request_changes'].includes(entry.name),
    )) {
      assert.equal(tool.annotations?.readOnlyHint, false);
      assert.equal(tool.annotations?.idempotentHint, false);
    }

    const prompts = await client.listPrompts();
    assert.deepEqual(
      prompts.prompts.map((prompt) => prompt.name).sort(),
      ['review_pr_correctness', 'review_pr_security'],
    );

    const prs = await client.callTool({
      name: 'list_prs',
      arguments: { owner: 'example', repo: 'project' },
    });
    assert.equal((prs.structuredContent as { returned: number }).returned, 1);

    const pr = await client.callTool({
      name: 'get_pr',
      arguments: { owner: 'example', repo: 'project', pull_number: 7 },
    });
    assert.equal((pr.structuredContent as { pull_number: number }).pull_number, 7);

    const diff = await client.callTool({
      name: 'get_pr_diff',
      arguments: { owner: 'example', repo: 'project', pull_number: 7 },
    });
    assert.equal((diff.structuredContent as { returned_files: number }).returned_files, 1);

    const comments = await client.callTool({
      name: 'list_pr_comments',
      arguments: { owner: 'example', repo: 'project', pull_number: 7 },
    });
    assert.equal((comments.structuredContent as { returned: number }).returned, 0);
  } finally {
    await client.close().catch(() => undefined);
    await api.close();
  }

  assert.doesNotMatch(stderr, /failed to start/i);
});
