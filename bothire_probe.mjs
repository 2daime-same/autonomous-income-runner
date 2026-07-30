import {createHash} from 'node:crypto';
import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const OUTPUT = process.env.BOTHIRE_OUTPUT ?? 'market-output/bothire-contract.json';
const USER_AGENT = 'autonomous-income-runner-bothire-probe/1.0';
const MAX_BYTES = 5_000_000;
const START_URLS = [
  'https://bothire.io/skill.md',
  'https://www.bothire.io/skill.md',
  'https://bothire.io/',
  'https://www.bothire.io/',
  'https://www.bothire.io/skills-catalog',
  'https://www.bothire.io/api-guide',
  'https://www.bothire.io/api-docs',
  'https://www.bothire.io/docs',
  'https://www.bothire.io/openapi.json',
  'https://www.bothire.io/api/openapi.json',
  'https://registry.npmjs.org/bothire/latest',
  'https://registry.npmjs.org/-/v1/search?text=bothire&size=30',
];
const ALLOWED_HOSTS = new Set([
  'bothire.io',
  'www.bothire.io',
  'api.bothire.io',
  'registry.npmjs.org',
]);
const NEEDLES = [
  'register', 'wallet', 'privateKey', 'apiKey', 'x402', 'USDC', 'Base',
  'create_post', 'createPost', 'postSkill', 'service', 'skill post',
  'discover', 'hire', 'accept', 'negotiate', 'message', 'inbox', 'task',
  'submit', 'deliver', 'complete', 'approve', 'release', 'refund', 'dispute',
  'balance', 'withdraw', 'payout', 'escrow', 'price', 'maxPrice',
  '/api/', '/v1/', 'MCP', 'endpoint', 'Authorization', 'X-API-Key',
];
const SECRET_KEY = /api.?key|authorization|bearer|secret|token|private.?key|mnemonic|seed|password|cookie|credential/i;

const now = () => new Date().toISOString();

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      output[key] = SECRET_KEY.test(key) ? '[REDACTED]' : sanitize(item);
    }
    return output;
  }
  if (typeof value === 'string') {
    return value
      .replace(/\b(?:bh|bothire|api|sk|pk)_[A-Za-z0-9._~+/=-]{8,}\b/gi, '[REDACTED]')
      .replace(/\b0x[0-9a-fA-F]{64}\b/g, '[REDACTED_PRIVATE_KEY]');
  }
  return value;
}

async function get(url, maxBytes = MAX_BYTES) {
  try {
    const response = await fetch(url, {
      headers: {Accept: 'application/json,text/markdown,text/html,*/*', 'User-Agent': USER_AGENT},
      redirect: 'follow',
      signal: AbortSignal.timeout(45_000),
    });
    const buffer = Buffer.from(await response.arrayBuffer()).subarray(0, maxBytes);
    const text = buffer.toString('utf8');
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch {}
    return {
      ok: response.ok,
      status: response.status,
      url,
      finalUrl: response.url,
      contentType: response.headers.get('content-type'),
      bytes: buffer.length,
      sha256: createHash('sha256').update(buffer).digest('hex'),
      text: json === null ? text : null,
      json,
    };
  } catch (error) {
    return {ok: false, url, error: `${error.name}: ${error.message}`};
  }
}

function scriptUrls(base, text) {
  const values = new Set();
  for (const match of text.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)) {
    const url = new URL(match[1], base);
    if (url.protocol === 'https:' && ALLOWED_HOSTS.has(url.hostname)) values.add(url.href);
  }
  return [...values].sort().slice(0, 100);
}

function contexts(text, radius = 450, perNeedle = 8) {
  const lower = text.toLowerCase();
  const output = [];
  for (const needle of NEEDLES) {
    const target = needle.toLowerCase();
    let start = 0;
    let count = 0;
    while (count < perNeedle) {
      const index = lower.indexOf(target, start);
      if (index < 0) break;
      output.push({needle, context: sanitize(text.slice(Math.max(0, index - radius), index + needle.length + radius))});
      start = index + target.length;
      count += 1;
    }
  }
  return output.slice(0, 300);
}

function candidateUrls(text, base = 'https://www.bothire.io/') {
  const values = new Set();
  const patterns = [
    /https?:\/\/[^\s"'<>\\]+/gi,
    /["'](\/api\/[^"']+)["']/gi,
    /["'](\/v\d+\/[^"']+)["']/gi,
    /["']([A-Za-z0-9_.-]+\.(?:register|create|post|list|discover|hire|accept|message|submit|deliver|complete|approve|release|refund|dispute|balance|withdraw|payout|status))["']/gi,
  ];
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      let value = match[1] ?? match[0];
      value = value.replace(/[\])},;`"']+$/g, '');
      if (value.startsWith('/')) value = new URL(value, base).href;
      if (value.length <= 800) values.add(value);
    }
  }
  return [...values].sort().slice(0, 2000);
}

function compactResponse(response) {
  const output = {};
  for (const key of ['ok', 'status', 'url', 'finalUrl', 'contentType', 'bytes', 'sha256', 'error']) {
    if (response[key] !== undefined && response[key] !== null) output[key] = response[key];
  }
  if (response.json !== null && response.json !== undefined) {
    const safe = sanitize(response.json);
    const serialized = JSON.stringify(safe);
    output.json = serialized.length <= 350_000 ? safe : {truncated: true, preview: serialized.slice(0, 350_000)};
  } else if (typeof response.text === 'string') {
    output.textPreview = sanitize(response.text.slice(0, 30_000));
    output.contexts = contexts(response.text);
    output.candidateUrls = candidateUrls(response.text, response.finalUrl ?? response.url);
  }
  return output;
}

function tarballUrl(registryPayload) {
  return registryPayload?.dist?.tarball ?? null;
}

async function extractTarball(url) {
  if (!url) return null;
  const result = await get(url, 20_000_000);
  if (!result.ok || !result.text) {
    // arrayBuffer was decoded as UTF-8 and is unsuitable for tarball extraction in-memory.
    // Re-fetch using curl to a temporary path; only the public package tarball is processed.
  }
  const archive = '/tmp/bothire-package.tgz';
  const extract = '/tmp/bothire-package';
  const download = await fetch(url, {headers: {'User-Agent': USER_AGENT}, signal: AbortSignal.timeout(60_000)});
  if (!download.ok) return {ok: false, status: download.status, url};
  await writeFile(archive, Buffer.from(await download.arrayBuffer()), {mode: 0o600});
  const {spawnSync} = await import('node:child_process');
  spawnSync('rm', ['-rf', extract], {stdio: 'ignore'});
  const unpack = spawnSync('tar', ['-xzf', archive, '-C', '/tmp'], {encoding: 'utf8'});
  if (unpack.status !== 0) return {ok: false, error: 'tar extraction failed'};
  const {readdir, readFile, stat} = await import('node:fs/promises');
  const root = '/tmp/package';
  const files = [];
  async function walk(directory, depth = 0) {
    if (depth > 5 || files.length >= 250) return;
    for (const entry of await readdir(directory, {withFileTypes: true})) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(full, depth + 1);
      else if (entry.isFile()) {
        const metadata = await stat(full);
        if (metadata.size > 2_000_000) continue;
        const relative = path.relative(root, full);
        if (/\.(?:js|mjs|cjs|ts|json|md|txt|yaml|yml)$/i.test(relative) || /(?:README|LICENSE|SKILL)/i.test(relative)) {
          const text = await readFile(full, 'utf8').catch(() => '');
          const foundContexts = contexts(text, 350, 5);
          const foundUrls = candidateUrls(text);
          files.push({path: relative, bytes: metadata.size, contexts: foundContexts, candidateUrls: foundUrls, preview: sanitize(text.slice(0, 15_000))});
        }
      }
    }
  }
  await walk(root);
  return {ok: true, url, fileCount: files.length, files};
}

async function atomicJson(file, value) {
  await mkdir(path.dirname(file), {recursive: true});
  const temporary = `${file}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {mode: 0o600});
  await rename(temporary, file);
}

const report = {generatedAt: now(), writesPerformed: [], pages: {}, scripts: {}, package: null};
const combined = [];
const discoveredScripts = new Set();
let registryLatest = null;

for (const url of START_URLS) {
  const response = await get(url);
  report.pages[url] = compactResponse(response);
  if (response.json !== null && response.json !== undefined) {
    combined.push(JSON.stringify(sanitize(response.json)));
    if (url.includes('registry.npmjs.org/bothire/latest')) registryLatest = response.json;
  } else if (typeof response.text === 'string') {
    combined.push(response.text);
    for (const script of scriptUrls(response.finalUrl ?? url, response.text)) discoveredScripts.add(script);
  }
}

for (const url of [...discoveredScripts].slice(0, 100)) {
  const response = await get(url);
  const text = typeof response.text === 'string' ? response.text : response.json ? JSON.stringify(response.json) : '';
  combined.push(text);
  const foundContexts = contexts(text, 400, 7);
  const foundUrls = candidateUrls(text, response.finalUrl ?? url);
  if (foundContexts.length || foundUrls.length) {
    report.scripts[url] = {
      ok: response.ok,
      status: response.status,
      finalUrl: response.finalUrl,
      bytes: response.bytes,
      sha256: response.sha256,
      contexts: foundContexts,
      candidateUrls: foundUrls,
    };
  }
}

report.package = await extractTarball(tarballUrl(registryLatest));
const allText = combined.join('\n');
report.summary = {
  scriptCount: discoveredScripts.size,
  combinedCandidateUrls: candidateUrls(allText),
  combinedContexts: contexts(allText, 650, 15),
};
await atomicJson(OUTPUT, report);
console.log(JSON.stringify({ok: true, output: OUTPUT, scripts: discoveredScripts.size, package: Boolean(report.package?.ok)}));
