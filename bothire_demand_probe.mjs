import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';

const ORIGIN = 'https://www.bothire.io';
const OUTPUT = 'market-output/bothire-demand.json';
const ROUTES = [
  '/api/hires?limit=200',
  '/api/hires?status=active&limit=200',
  '/api/hires?status=completed&limit=200',
  '/api/transactions?limit=200',
  '/api/activity?limit=200',
  '/api/feed?limit=200',
  '/api/posts?status=active&sort=popular&limit=200',
  '/api/posts?status=active&sort=hires&limit=200',
  '/api/posts?status=active&limit=200',
  '/api/stats',
];

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      output[key] = /api.?key|authorization|token|secret|private|credential|password|cookie|mnemonic|seed/i.test(key)
        ? '[REDACTED]'
        : sanitize(item);
    }
    return output;
  }
  if (typeof value === 'string') {
    return value
      .replace(/\bbh_[A-Za-z0-9._~+/=-]{8,}\b/g, '[REDACTED]')
      .replace(/\b0x[0-9a-fA-F]{64}\b/g, '[REDACTED_PRIVATE_KEY]');
  }
  return value;
}

async function get(route) {
  try {
    const response = await fetch(`${ORIGIN}${route}`, {
      headers: {Accept: 'application/json', 'User-Agent': 'autonomous-income-runner-bothire-demand-probe/1.0'},
      redirect: 'follow',
      signal: AbortSignal.timeout(45_000),
    });
    const text = await response.text();
    let payload;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = {text: text.slice(0, 4000)}; }
    return {route, ok: response.ok, status: response.status, finalUrl: response.url, payload: sanitize(payload)};
  } catch (error) {
    return {route, ok: false, error: `${error.name}: ${error.message}`};
  }
}

function arrays(value, pathName = '$', output = []) {
  if (Array.isArray(value)) {
    if (value.every(item => item && typeof item === 'object' && !Array.isArray(item))) output.push({path: pathName, items: value});
    value.forEach((item, index) => arrays(item, `${pathName}[${index}]`, output));
  } else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) arrays(item, `${pathName}.${key}`, output);
  }
  return output;
}

function number(value) {
  const result = Number(typeof value === 'string' ? value.replace(/[^0-9.-]/g, '') : value);
  return Number.isFinite(result) ? result : null;
}

function compactPost(item) {
  return {
    id: item._id ?? item.id,
    bot_id: item.bot_id ?? item.botId,
    bot_name: item.bot_name ?? item.botName,
    title: item.title,
    description: typeof item.description === 'string' ? item.description.slice(0, 1000) : null,
    tags: item.tags,
    price_usdc: number(item.price_usdc ?? item.price),
    price_type: item.price_type ?? item.priceType,
    status: item.status,
    views: number(item.views),
    hires_count: number(item.hires_count ?? item.hire_count ?? item.hiresCount),
    created_at: item.created_at ?? item.createdAt,
    updated_at: item.updated_at ?? item.updatedAt,
  };
}

function compactHire(item) {
  return {
    id: item._id ?? item.id ?? item.hire_id,
    post_id: item.post_id ?? item.postId,
    hirer_bot_id: item.hirer_bot_id ?? item.hirerBotId,
    provider_bot_id: item.provider_bot_id ?? item.providerBotId,
    status: item.status,
    amount_usdc: number(item.amount_usdc ?? item.price_usdc ?? item.amount),
    payment_mode: item.payment_mode ?? item.paymentMode,
    payment_status: item.payment_status ?? item.paymentStatus,
    payment_tx_hash: item.payment_tx_hash ?? item.paymentTxHash,
    release_tx_hash: item.release_tx_hash ?? item.releaseTxHash,
    created_at: item.created_at ?? item.createdAt,
    completed_at: item.completed_at ?? item.completedAt,
  };
}

function compactTransaction(item) {
  return {
    id: item._id ?? item.id,
    hire_id: item.hire_id ?? item.hireId,
    status: item.status,
    amount_usdc: number(item.amount_usdc ?? item.amount),
    tx_hash: item.tx_hash ?? item.txHash,
    type: item.type,
    created_at: item.created_at ?? item.createdAt,
  };
}

const results = [];
const posts = new Map();
const hires = new Map();
const transactions = new Map();
let stats = null;
for (const route of ROUTES) {
  const response = await get(route);
  const shapes = arrays(response.payload);
  for (const shape of shapes) {
    for (const item of shape.items) {
      if ((item.title || item.description) && (item.price_usdc !== undefined || item.hires_count !== undefined || item.tags)) {
        const post = compactPost(item);
        if (post.id) posts.set(String(post.id), post);
      }
      if ((item.post_id || item.provider_bot_id || item.hirer_bot_id) && (item.status || item.amount_usdc !== undefined)) {
        const hire = compactHire(item);
        if (hire.id) hires.set(String(hire.id), hire);
      }
      if ((item.tx_hash || item.txHash || item.hire_id) && (item.amount_usdc !== undefined || item.type)) {
        const transaction = compactTransaction(item);
        if (transaction.id || transaction.tx_hash) transactions.set(String(transaction.id ?? transaction.tx_hash), transaction);
      }
    }
  }
  if (route === '/api/stats' && response.ok) stats = response.payload;
  results.push({
    route,
    ok: response.ok,
    status: response.status,
    finalUrl: response.finalUrl,
    topLevelKeys: response.payload && typeof response.payload === 'object' && !Array.isArray(response.payload) ? Object.keys(response.payload) : [],
    arrayShapes: shapes.map(shape => ({path: shape.path, count: shape.items.length})).slice(0, 30),
    payloadPreview: shapes.length ? undefined : response.payload,
  });
}

const postList = [...posts.values()];
const hireList = [...hires.values()];
const transactionList = [...transactions.values()];
const purchasedPosts = postList
  .filter(post => (post.hires_count ?? 0) > 0)
  .sort((a, b) => (b.hires_count ?? 0) - (a.hires_count ?? 0));
const recentCompleted = hireList
  .filter(hire => String(hire.status ?? '').toLowerCase() === 'completed')
  .sort((a, b) => (Date.parse(b.completed_at ?? b.created_at ?? '') || 0) - (Date.parse(a.completed_at ?? a.created_at ?? '') || 0));
const paidTransactions = transactionList
  .filter(transaction => (transaction.amount_usdc ?? 0) > 0 || transaction.tx_hash)
  .sort((a, b) => (Date.parse(b.created_at ?? '') || 0) - (Date.parse(a.created_at ?? '') || 0));

const report = {
  generatedAt: new Date().toISOString(),
  writesPerformed: [],
  results,
  stats,
  uniquePostCount: postList.length,
  uniqueHireCount: hireList.length,
  uniqueTransactionCount: transactionList.length,
  purchasedPostCount: purchasedPosts.length,
  completedHireCount: recentCompleted.length,
  paidTransactionCount: paidTransactions.length,
  purchasedPosts: purchasedPosts.slice(0, 100),
  recentCompletedHires: recentCompleted.slice(0, 100),
  paidTransactions: paidTransactions.slice(0, 100),
  newestActivePosts: postList
    .filter(post => String(post.status ?? '').toLowerCase() === 'active')
    .sort((a, b) => (Date.parse(b.created_at ?? '') || 0) - (Date.parse(a.created_at ?? '') || 0))
    .slice(0, 100),
};

await mkdir(path.dirname(OUTPUT), {recursive: true});
const temporary = `${OUTPUT}.tmp`;
await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`, {mode: 0o600});
await rename(temporary, OUTPUT);
console.log(JSON.stringify({ok: true, posts: postList.length, purchased: purchasedPosts.length, hires: hireList.length, completed: recentCompleted.length, transactions: paidTransactions.length}));
