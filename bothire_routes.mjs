import {createHash} from 'node:crypto';
import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';

const ORIGIN = 'https://www.bothire.io';
const OUTPUT = 'market-output/bothire-routes.json';
const USER_AGENT = 'autonomous-income-runner-bothire-routes/1.0';
const MARKERS = [
  'createTask', 'searchTasks', 'taskDetails', 'updateTask', 'claimTask', 'completeTask',
  'createPost', 'searchPosts', 'myPosts', 'myHires', 'listHires',
  'generate-wallet', 'bots/register', 'hires?role=provider', '/inbox', '/deliver',
  'paymentIntent', 'escrowLock', 'escrowRelease', 'transactions', 'wallet', 'balance',
];

async function get(url) {
  const response = await fetch(url, {
    headers: {Accept: 'text/html,text/javascript,text/markdown,*/*', 'User-Agent': USER_AGENT},
    redirect: 'follow',
    signal: AbortSignal.timeout(45_000),
  });
  const buffer = Buffer.from(await response.arrayBuffer());
  return {
    ok: response.ok,
    status: response.status,
    url: response.url,
    contentType: response.headers.get('content-type'),
    bytes: buffer.length,
    sha256: createHash('sha256').update(buffer).digest('hex'),
    text: buffer.toString('utf8'),
  };
}

function scripts(base, html) {
  const output = new Set();
  for (const match of html.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)) {
    const url = new URL(match[1], base);
    if (url.hostname === 'www.bothire.io' || url.hostname === 'bothire.io') output.add(url.href);
  }
  return [...output].sort();
}

function extractPaths(text) {
  const output = new Set();
  const patterns = [
    /\/api\/[A-Za-z0-9_?&=./:${}\[\]-]+/g,
    /https:\/\/www\.bothire\.io\/api\/[A-Za-z0-9_?&=./:${}\[\]-]+/g,
  ];
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      const value = match[0].replace(/[\])},;`"']+$/g, '');
      if (value.length <= 500) output.add(value);
    }
  }
  return [...output].sort();
}

function markerContexts(text, radius = 1200) {
  const lower = text.toLowerCase();
  const output = [];
  for (const marker of MARKERS) {
    const target = marker.toLowerCase();
    let start = 0;
    let count = 0;
    while (count < 5) {
      const index = lower.indexOf(target, start);
      if (index < 0) break;
      output.push({marker, context: text.slice(Math.max(0, index - radius), index + marker.length + radius)});
      start = index + target.length;
      count += 1;
    }
  }
  return output;
}

async function atomicJson(file, value) {
  await mkdir(path.dirname(file), {recursive: true});
  const temporary = `${file}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {mode: 0o600});
  await rename(temporary, file);
}

const home = await get(`${ORIGIN}/`);
const skill = await get(`${ORIGIN}/skill.md`);
const scriptUrls = scripts(home.url, home.text);
const assets = [];
const allPaths = new Set([...extractPaths(home.text), ...extractPaths(skill.text)]);
const contexts = [...markerContexts(skill.text)];
for (const url of scriptUrls) {
  const response = await get(url);
  const paths = extractPaths(response.text);
  const found = markerContexts(response.text);
  for (const item of paths) allPaths.add(item);
  if (paths.length || found.length) {
    assets.push({url, status: response.status, bytes: response.bytes, sha256: response.sha256, paths, contexts: found});
    contexts.push(...found);
  }
}
await atomicJson(OUTPUT, {
  generatedAt: new Date().toISOString(),
  writesPerformed: [],
  skillStatus: skill.status,
  scriptCount: scriptUrls.length,
  apiPaths: [...allPaths].sort(),
  contexts: contexts.slice(0, 220),
  assets,
});
console.log(JSON.stringify({ok: true, paths: allPaths.size, assets: assets.length}));
