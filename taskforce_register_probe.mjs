import {chmod, mkdir, rename, rm, writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import process from 'node:process';

const HOSTS = ['https://taskforce.app', 'https://www.task-force.app', 'https://task-force.app'];
const OUTPUT = 'taskforce-probe-output/result.json';
const PRIVATE_OUTPUT = 'taskforce-probe-output/private-state.cms';
const CERTIFICATE = 'keys/superteam-state-public.crt';
const RUN_ID = process.env.GITHUB_RUN_ID ?? String(Date.now());
const BASE_NAME = `BoundaryLedger-TaskForce-Probe-${RUN_ID}`.slice(0, 88);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const result = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = /api.?key|authorization|token|secret|private|credential|password|cookie|email/i.test(key)
        ? '[REDACTED]'
        : sanitize(item);
    }
    return result;
  }
  if (typeof value === 'string') {
    return value
      .replace(/\bapv_[A-Za-z0-9._~+/=-]{8,}\b/g, '[REDACTED]')
      .replace(/\b0x[0-9a-fA-F]{64}\b/g, '[REDACTED_PRIVATE_KEY]');
  }
  return value;
}

async function atomicJson(file, value) {
  await mkdir(path.dirname(file), {recursive: true});
  const temporary = `${file}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {mode: 0o600});
  await rename(temporary, file);
}

function run(command, args) {
  return spawnSync(command, args, {cwd: process.cwd(), encoding: 'utf8', stdio: 'pipe'});
}

async function request(host, method, endpoint, {body, apiKey} = {}) {
  const headers = {Accept: 'application/json'};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
    headers.Authorization = `Bearer ${apiKey}`;
  }
  const response = await fetch(`${host}${endpoint}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: 'follow',
    signal: AbortSignal.timeout(45_000),
  });
  const text = await response.text();
  let payload;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = {text: text.slice(0, 3000)}; }
  return {ok: response.ok, status: response.status, finalUrl: response.url, payload};
}

function find(value, keys) {
  if (Array.isArray(value)) {
    for (const item of value) {
      const result = find(item, keys);
      if (result) return result;
    }
    return null;
  }
  if (!value || typeof value !== 'object') return null;
  for (const [key, item] of Object.entries(value)) {
    if (keys.has(key.toLowerCase()) && typeof item === 'string' && item) return item;
    const result = find(item, keys);
    if (result) return result;
  }
  return null;
}

async function encryptPrivate(value) {
  const plain = '/tmp/taskforce-probe-private.json';
  await writeFile(plain, `${JSON.stringify(value, null, 2)}\n`, {mode: 0o600});
  await chmod(plain, 0o600);
  await mkdir(path.dirname(PRIVATE_OUTPUT), {recursive: true});
  const result = run('openssl', ['cms', '-encrypt', '-binary', '-aes256', '-outform', 'DER', '-in', plain, '-out', PRIVATE_OUTPUT, CERTIFICATE]);
  await rm(plain, {force: true});
  if (result.status !== 0) throw new Error('credential encryption failed');
}

const report = {
  generatedAt: new Date().toISOString(),
  writesPerformed: [],
  expensesUsd: 0,
  hosts: [],
  success: false,
};

try {
  for (let hostIndex = 0; hostIndex < HOSTS.length && !report.success; hostIndex += 1) {
    const host = HOSTS[hostIndex];
    const hostReport = {host, attempts: []};
    report.hosts.push(hostReport);
    for (let attempt = 0; attempt < 3 && !report.success; attempt += 1) {
      const name = `${BASE_NAME}-${hostIndex + 1}`.slice(0, 100);
      let response;
      try {
        response = await request(host, 'POST', '/api/agent/register', {
          body: {
            name,
            capabilities: ['research', 'writing', 'documentation', 'testing', 'data-analysis', 'python', 'javascript'],
          },
        });
      } catch (error) {
        hostReport.attempts.push({attempt: attempt + 1, error: `${error.name}: ${error.message}`});
        await sleep(2_000 * (attempt + 1));
        continue;
      }
      hostReport.attempts.push({
        attempt: attempt + 1,
        ok: response.ok,
        status: response.status,
        finalUrl: response.finalUrl,
        payload: sanitize(response.payload),
      });
      if (response.ok) {
        const apiKey = find(response.payload, new Set(['apikey', 'api_key', 'key']));
        const agentId = find(response.payload, new Set(['agentid', 'agent_id', 'id']));
        const walletAddress = find(response.payload, new Set(['walletaddress', 'wallet_address']));
        if (!apiKey || !agentId) throw new Error('successful registration omitted API key or agent ID');
        await encryptPrivate({host, apiKey, agentId, walletAddress, name});
        report.writesPerformed.push('agent_registration');
        report.success = true;
        report.selectedHost = host;
        report.registration = sanitize({agentId, walletAddress, name, status: response.payload?.agent?.status});
        const tasks = await request(host, 'GET', '/api/agent/tasks?status=ACTIVE&limit=100', {apiKey});
        report.taskInventory = sanitize({ok: tasks.ok, status: tasks.status, finalUrl: tasks.finalUrl, payload: tasks.payload});
        break;
      }
      if (response.status < 500) break;
      await sleep(2_000 * (2 ** attempt));
    }
  }
} catch (error) {
  report.error = `${error.name}: ${error.message}`;
}

report.finishedAt = new Date().toISOString();
await atomicJson(OUTPUT, report);
if (!report.success) process.exitCode = 1;
