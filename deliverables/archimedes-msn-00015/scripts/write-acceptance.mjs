#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const owner = String(process.env.GITHUB_WRITE_ACCEPTANCE_OWNER ?? '').trim();
const repo = String(process.env.GITHUB_WRITE_ACCEPTANCE_REPO ?? '').trim();
const pullNumber = Number(process.env.GITHUB_WRITE_ACCEPTANCE_PR ?? '0');
const fixturePath = String(process.env.GITHUB_WRITE_ACCEPTANCE_PATH ?? '').trim();
const token = String(process.env.GITHUB_TOKEN ?? '').trim();

if (!owner || !repo || !Number.isSafeInteger(pullNumber) || pullNumber < 1 || !fixturePath || !token) {
  throw new Error(
    'GITHUB_WRITE_ACCEPTANCE_OWNER, GITHUB_WRITE_ACCEPTANCE_REPO, ' +
      'GITHUB_WRITE_ACCEPTANCE_PR, GITHUB_WRITE_ACCEPTANCE_PATH, and GITHUB_TOKEN are required.',
  );
}

function stringEnvironment() {
  const output = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && key !== 'GITHUB_TOKEN') {
      output[key] = value;
    }
  }
  return output;
}

function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} did not return structured object content.`);
  }
  return value;
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

const runId = String(process.env.GITHUB_RUN_ID ?? Date.now());
const runAttempt = String(process.env.GITHUB_RUN_ATTEMPT ?? '1');
const marker = `MSN-00015 write acceptance ${runId}:${runAttempt}`;
const markerSha256 = createHash('sha256').update(marker).digest('hex');

const transport = new StdioClientTransport({
  command: process.execPath,
  args: ['dist/index.js'],
  cwd: PROJECT_ROOT,
  stderr: 'pipe',
  env: {
    ...stringEnvironment(),
    GITHUB_AUTH_MODE: 'pat',
    GITHUB_READ_TOKEN: token,
    GITHUB_WRITE_TOKEN: token,
    GITHUB_ALLOW_WRITES: 'true',
    GITHUB_MAX_RETRIES: '0',
    GITHUB_TIMEOUT_MS: '15000',
  },
});

let stderr = '';
transport.stderr?.on('data', (chunk) => {
  stderr += String(chunk);
});

const client = new Client({ name: 'msn-00015-write-acceptance', version: '1.0.0' });
let evidence;
try {
  await client.connect(transport);

  const diffResult = await client.callTool({
    name: 'get_pr_diff',
    arguments: {
      owner,
      repo,
      pull_number: pullNumber,
      max_files: 100,
      max_lines_per_file: 500,
      include_patch: false,
    },
  });
  if (diffResult.isError) {
    throw new Error('get_pr_diff returned an MCP error.');
  }
  const diff = object(diffResult.structuredContent, 'get_pr_diff');
  const file = array(diff.files).find(
    (candidate) => candidate && typeof candidate === 'object' && candidate.path === fixturePath,
  );
  if (!file || typeof file !== 'object') {
    throw new Error(`Acceptance fixture ${fixturePath} was not present in the PR diff.`);
  }
  const lines = array(file.hunks).flatMap((hunk) =>
    hunk && typeof hunk === 'object' ? array(hunk.lines) : [],
  );
  const location =
    lines.find(
      (line) =>
        line &&
        typeof line === 'object' &&
        line.kind === 'addition' &&
        Number.isSafeInteger(line.newLine) &&
        line.newLine > 0,
    ) ??
    lines.find(
      (line) =>
        line &&
        typeof line === 'object' &&
        Number.isSafeInteger(line.newLine) &&
        line.newLine > 0,
    );
  if (!location || typeof location !== 'object') {
    throw new Error('No RIGHT-side commentable line was found in the acceptance fixture.');
  }

  const line = Number(location.newLine);
  const startedAtMs = Date.now();
  const commentResult = await client.callTool({
    name: 'post_review_comment',
    arguments: {
      owner,
      repo,
      pull_number: pullNumber,
      body: marker,
      path: fixturePath,
      line,
      side: 'RIGHT',
      confirm: true,
    },
  });
  if (commentResult.isError) {
    throw new Error('post_review_comment returned an MCP error.');
  }
  const posted = object(commentResult.structuredContent, 'post_review_comment');
  const postedItem = object(posted.item, 'post_review_comment item');
  const commentId = Number(postedItem.id);
  const commentUrl = typeof postedItem.html_url === 'string' ? postedItem.html_url : null;
  if (!Number.isSafeInteger(commentId) || commentId < 1 || !commentUrl) {
    throw new Error('Posted review comment did not include an ID and public URL.');
  }

  let visibleAfterMs = null;
  let pollCount = 0;
  while (Date.now() - startedAtMs <= 5_000) {
    pollCount += 1;
    const commentsResult = await client.callTool({
      name: 'list_pr_comments',
      arguments: {
        owner,
        repo,
        pull_number: pullNumber,
        include_issue_comments: false,
        include_reviews: false,
        include_inline_comments: true,
        max_items: 500,
      },
    });
    if (!commentsResult.isError) {
      const comments = object(commentsResult.structuredContent, 'list_pr_comments');
      const found = array(comments.items).some(
        (item) =>
          item &&
          typeof item === 'object' &&
          (item.id === commentId || item.body === marker),
      );
      if (found) {
        visibleAfterMs = Date.now() - startedAtMs;
        break;
      }
    }
    await sleep(250);
  }

  if (visibleAfterMs === null || visibleAfterMs > 5_000) {
    throw new Error('Posted review comment was not observable through GitHub within five seconds.');
  }

  evidence = {
    ok: true,
    mission: 'MSN-00015',
    operation: 'post_review_comment',
    repository: `${owner}/${repo}`,
    pull_number: pullNumber,
    path: fixturePath,
    line,
    side: 'RIGHT',
    comment_id: commentId,
    comment_url: commentUrl,
    marker_sha256: markerSha256,
    request_duration_ms: posted.request_duration_ms ?? null,
    visible_after_ms: visibleAfterMs,
    poll_count: pollCount,
    write_count: 1,
    verification: 'GitHub inline review comment returned by list_pr_comments within five seconds.',
    generated_at: new Date().toISOString(),
  };
} finally {
  await client.close().catch(() => undefined);
}

if (!evidence) {
  throw new Error(`Acceptance evidence was not produced. Server stderr length: ${stderr.length}`);
}

await mkdir(path.join(PROJECT_ROOT, 'dist-submission'), { recursive: true });
await writeFile(
  path.join(PROJECT_ROOT, 'dist-submission', 'write-acceptance.json'),
  `${JSON.stringify(evidence, null, 2)}\n`,
  'utf8',
);
process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
