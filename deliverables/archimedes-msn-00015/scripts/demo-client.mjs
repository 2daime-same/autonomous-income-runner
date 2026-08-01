#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import readline from 'node:readline';

const outputDirectory = path.resolve(process.env.DEMO_OUTPUT_DIR ?? 'dist-submission/demo');
const owner = String(process.env.DEMO_GITHUB_OWNER ?? '2daime-same').trim();
const repo = String(process.env.DEMO_GITHUB_REPO ?? 'autonomous-income-runner').trim();
const pullNumber = Number(process.env.DEMO_GITHUB_PR ?? '7');
const expectedCommentId = Number(process.env.DEMO_EXPECTED_COMMENT_ID ?? '3695975388');
const serverPath = path.resolve(process.env.DEMO_SERVER_PATH ?? 'dist/index.js');

if (!owner || !repo || !Number.isSafeInteger(pullNumber) || pullNumber < 1) {
  throw new Error('Invalid demo repository or pull request configuration.');
}

const cleanEnvironment = Object.fromEntries(
  Object.entries(process.env).filter(([, value]) => typeof value === 'string'),
);
Object.assign(cleanEnvironment, {
  GITHUB_AUTH_MODE: cleanEnvironment.GITHUB_TOKEN ? 'pat' : 'none',
  GITHUB_READ_TOKEN: cleanEnvironment.GITHUB_TOKEN ?? '',
  GITHUB_WRITE_TOKEN: '',
  GITHUB_ALLOW_WRITES: 'false',
});

const child = spawn(process.execPath, [serverPath], {
  cwd: process.cwd(),
  env: cleanEnvironment,
  stdio: ['pipe', 'pipe', 'pipe'],
});

const lines = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
const pending = new Map();
const stderr = [];
let nextId = 1;
let fatal;

child.stderr.setEncoding('utf8');
child.stderr.on('data', (chunk) => stderr.push(String(chunk)));
child.on('error', (error) => {
  fatal = error;
  for (const { reject } of pending.values()) reject(error);
  pending.clear();
});
child.on('exit', (code, signal) => {
  if (pending.size > 0) {
    const error = fatal ?? new Error(`MCP server exited before replying (code=${code}, signal=${signal}).`);
    for (const { reject } of pending.values()) reject(error);
    pending.clear();
  }
});

lines.on('line', (line) => {
  const text = line.trim();
  if (!text) return;
  let message;
  try {
    message = JSON.parse(text);
  } catch {
    stderr.push(`unexpected stdout: ${text}`);
    return;
  }
  if (message && Object.hasOwn(message, 'id')) {
    const waiter = pending.get(message.id);
    if (waiter) {
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
      else waiter.resolve(message.result);
    }
  }
});

function send(payload) {
  child.stdin.write(`${JSON.stringify(payload)}\n`);
}

function request(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Timed out waiting for ${method}.`));
    }, 30_000);
    pending.set(id, {
      resolve(value) {
        clearTimeout(timer);
        resolve(value);
      },
      reject(error) {
        clearTimeout(timer);
        reject(error);
      },
    });
    send({ jsonrpc: '2.0', id, method, params });
  });
}

function notify(method, params = {}) {
  send({ jsonrpc: '2.0', method, params });
}

function textContent(result) {
  if (!result || !Array.isArray(result.content)) return '';
  return result.content
    .filter((item) => item && item.type === 'text' && typeof item.text === 'string')
    .map((item) => item.text)
    .join('\n');
}

function structured(result) {
  if (result && result.structuredContent && typeof result.structuredContent === 'object') {
    return result.structuredContent;
  }
  const text = textContent(result).trim();
  if (text.startsWith('{') || text.startsWith('[')) {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }
  return null;
}

function findCommentId(value, wanted) {
  if (value === null || value === undefined) return false;
  if (typeof value === 'number') return value === wanted;
  if (typeof value === 'string') return value === String(wanted) || value.includes(String(wanted));
  if (Array.isArray(value)) return value.some((item) => findCommentId(item, wanted));
  if (typeof value === 'object') return Object.values(value).some((item) => findCommentId(item, wanted));
  return false;
}

async function callTool(name, args) {
  const started = performance.now();
  const result = await request('tools/call', { name, arguments: args });
  return {
    name,
    duration_ms: Math.round(performance.now() - started),
    is_error: Boolean(result?.isError),
    structured: structured(result),
    text: textContent(result).slice(0, 12_000),
  };
}

try {
  const initialized = await request('initialize', {
    protocolVersion: '2025-06-18',
    capabilities: {},
    clientInfo: { name: 'archimedes-demo-client', version: '1.0.0' },
  });
  notify('notifications/initialized');

  const toolsResult = await request('tools/list');
  const promptsResult = await request('prompts/list');
  const toolNames = (toolsResult.tools ?? []).map((tool) => tool.name);
  const promptNames = (promptsResult.prompts ?? []).map((prompt) => prompt.name);

  const expectedTools = [
    'list_prs',
    'get_pr',
    'get_pr_diff',
    'list_pr_comments',
    'post_review_comment',
    'submit_review',
    'add_labels',
    'request_changes',
  ];
  for (const tool of expectedTools) {
    if (!toolNames.includes(tool)) throw new Error(`Required tool was not registered: ${tool}`);
  }

  const calls = [];
  calls.push(await callTool('list_prs', { owner, repo, state: 'all', max_items: 10 }));
  calls.push(await callTool('get_pr', { owner, repo, pull_number: pullNumber }));
  calls.push(await callTool('get_pr_diff', {
    owner,
    repo,
    pull_number: pullNumber,
    max_files: 10,
    max_lines_per_file: 100,
    include_patch: false,
  }));
  calls.push(await callTool('list_pr_comments', {
    owner,
    repo,
    pull_number: pullNumber,
    max_items: 100,
  }));

  const commentsCall = calls.find((call) => call.name === 'list_pr_comments');
  const commentVisible = findCommentId(commentsCall?.structured, expectedCommentId)
    || findCommentId(commentsCall?.text, expectedCommentId);
  if (!commentVisible) {
    throw new Error(`Acceptance comment ${expectedCommentId} was not visible through list_pr_comments.`);
  }

  const writeGate = await callTool('add_labels', {
    owner,
    repo,
    pull_number: pullNumber,
    labels: ['demo-never-applied'],
    confirm: false,
  });
  if (!writeGate.is_error) {
    throw new Error('Write-gate demonstration unexpectedly succeeded.');
  }

  const evidence = {
    ok: true,
    generated_at: new Date().toISOString(),
    protocol_version: initialized.protocolVersion ?? null,
    server_info: initialized.serverInfo ?? null,
    repository: `${owner}/${repo}`,
    pull_number: pullNumber,
    registered_tools: toolNames,
    registered_prompts: promptNames,
    read_calls: calls,
    prior_acceptance_comment_id: expectedCommentId,
    prior_acceptance_comment_visible: commentVisible,
    write_gate: {
      process_gate: 'GITHUB_ALLOW_WRITES=false',
      call_confirm: false,
      rejected: writeGate.is_error,
      evidence: writeGate,
    },
    writes_performed: [],
    stderr: stderr.join('').slice(0, 12_000),
  };

  await mkdir(outputDirectory, { recursive: true });
  await writeFile(path.join(outputDirectory, 'mcp-demo-evidence.json'), `${JSON.stringify(evidence, null, 2)}\n`);

  const transcript = [
    '# Archimedes GitHub PR MCP — deterministic demo transcript',
    '',
    `Generated: ${evidence.generated_at}`,
    `Server: ${evidence.server_info?.name ?? 'unknown'} ${evidence.server_info?.version ?? ''}`,
    `Protocol: ${evidence.protocol_version}`,
    `Repository: ${evidence.repository} PR #${pullNumber}`,
    '',
    `Registered tools (${toolNames.length}):`,
    ...toolNames.map((name) => `  - ${name}`),
    '',
    `Registered prompts (${promptNames.length}):`,
    ...promptNames.map((name) => `  - ${name}`),
    '',
    'Read calls:',
    ...calls.map((call) => `  - ${call.name}: ${call.duration_ms} ms, error=${call.is_error}`),
    '',
    `Prior acceptance inline comment ${expectedCommentId}: visible=${commentVisible}`,
    `Write gate (writes disabled + confirm=false): rejected=${writeGate.is_error}`,
    'Writes performed during this demo: 0',
    '',
  ].join('\n');
  await writeFile(path.join(outputDirectory, 'mcp-demo-transcript.txt'), transcript);
  process.stdout.write(transcript);
} finally {
  try { child.stdin.end(); } catch {}
  setTimeout(() => child.kill('SIGTERM'), 300).unref();
}
