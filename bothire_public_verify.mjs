import {mkdir, readFile, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';

const ORIGIN = 'https://www.bothire.io';
const OUTPUT = 'market-output/bothire-live-verification.json';
const state = JSON.parse(await readFile('bothire-output/public-state.json', 'utf8'));
const botId = state.botId;
const botName = state.botName;
const wallet = state.walletAddress;
const query = encodeURIComponent('BoundaryLedger');
const routes = [
  `/api/bots/${encodeURIComponent(botId)}`,
  `/api/bots/${encodeURIComponent(botId)}/skills`,
  `/api/bots/search?keyword=${query}`,
  `/api/bots/search?keyword=${encodeURIComponent(botName)}`,
  `/api/posts?bot_id=${encodeURIComponent(botId)}&limit=100`,
  `/api/posts?provider_bot_id=${encodeURIComponent(botId)}&limit=100`,
  `/api/posts?search=${query}&limit=100`,
  `/api/posts?keyword=${query}&limit=100`,
  `/api/posts?wallet_address=${encodeURIComponent(wallet)}&limit=100`,
  `/api/skills/search?keyword=json`,
  `/api/skills/search?keyword=documentation`,
  `/api/tasks?status=open&limit=100`,
  `/api/tasks?status=active&limit=100`,
  `/api/tasks/search?status=open&limit=100`,
  `/api/hire-requests?status=open&limit=100`,
  `/api/requests?status=open&limit=100`,
  `/api/stats`,
];

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      output[key] = /api.?key|authorization|token|secret|private|credential|password|cookie/i.test(key)
        ? '[REDACTED]'
        : sanitize(item);
    }
    return output;
  }
  if (typeof value === 'string') {
    return value.replace(/\bbh_[A-Za-z0-9._~+/=-]{8,}\b/g, '[REDACTED]').replace(/\b0x[0-9a-fA-F]{64}\b/g, '[REDACTED_PRIVATE_KEY]');
  }
  return value;
}

async function get(route) {
  try {
    const response = await fetch(`${ORIGIN}${route}`, {
      headers: {Accept: 'application/json', 'User-Agent': 'autonomous-income-runner-bothire-live-verify/1.0'},
      redirect: 'follow',
      signal: AbortSignal.timeout(45_000),
    });
    const text = await response.text();
    let payload;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = {text: text.slice(0, 10_000)}; }
    return {route, ok: response.ok, status: response.status, finalUrl: response.url, payload: sanitize(payload)};
  } catch (error) {
    return {route, ok: false, error: `${error.name}: ${error.message}`};
  }
}

const results = [];
for (const route of routes) results.push(await get(route));
const report = {
  generatedAt: new Date().toISOString(),
  writesPerformed: [],
  botId,
  botName,
  walletAddress: wallet,
  results,
};
await mkdir(path.dirname(OUTPUT), {recursive: true});
const temporary = `${OUTPUT}.tmp`;
await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`, {mode: 0o600});
await rename(temporary, OUTPUT);
console.log(JSON.stringify({ok: true, routes: results.length}));
