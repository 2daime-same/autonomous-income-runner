import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';

const ORIGIN = 'https://www.bothire.io';
const OUTPUT = 'market-output/bothire-tasks.json';
const ROUTES = [
  '/api/tasks/search?status=open&limit=100',
  '/api/tasks/search?status=active&limit=100',
  '/api/tasks/search?limit=100',
  '/api/tasks/search?status=open&sort=newest&limit=100',
  '/api/tasks/search?status=open&funded=true&limit=100',
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
      headers: {Accept: 'application/json', 'User-Agent': 'autonomous-income-runner-bothire-task-probe/1.0'},
      redirect: 'follow',
      signal: AbortSignal.timeout(45_000),
    });
    const text = await response.text();
    let payload;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = {text: text.slice(0, 5000)}; }
    return {route, ok: response.ok, status: response.status, finalUrl: response.url, payload: sanitize(payload)};
  } catch (error) {
    return {route, ok: false, error: `${error.name}: ${error.message}`};
  }
}

function collectArrays(value, pathName = '$', output = []) {
  if (Array.isArray(value)) {
    if (value.every(item => item && typeof item === 'object' && !Array.isArray(item))) {
      output.push({path: pathName, items: value});
    }
    value.forEach((item, index) => collectArrays(item, `${pathName}[${index}]`, output));
  } else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) collectArrays(item, `${pathName}.${key}`, output);
  }
  return output;
}

function looksLikeTask(item) {
  return Boolean(item && typeof item === 'object' && (item.title || item.description) && (item._id || item.id || item.task_id || item.taskId));
}

function compactTask(task) {
  return {
    id: task._id ?? task.id ?? task.task_id ?? task.taskId,
    title: task.title ?? null,
    description: typeof task.description === 'string' ? task.description.slice(0, 1500) : null,
    status: task.status ?? null,
    budget: task.budget ?? task.budget_usdc ?? task.reward ?? task.amount ?? null,
    required_skills: task.required_skills ?? task.skills ?? null,
    assigned_bot_id: task.assigned_bot_id ?? task.assignedBotId ?? null,
    payment_tx_hash: task.payment_tx_hash ?? task.paymentTxHash ?? null,
    escrow_address: task.escrow_address ?? task.escrowAddress ?? null,
    payment_status: task.payment_status ?? task.paymentStatus ?? task.funding_status ?? task.fundingStatus ?? null,
    creator_wallet_address: task.creator_wallet_address ?? task.creatorWalletAddress ?? null,
    deadline: task.deadline ?? null,
    created_at: task.created_at ?? task.createdAt ?? null,
    updated_at: task.updated_at ?? task.updatedAt ?? null,
  };
}

function freshness(createdAt) {
  const time = Date.parse(createdAt ?? '');
  return Number.isFinite(time) ? (Date.now() - time) / 86_400_000 : null;
}

function fundingEvidence(task) {
  return Boolean(
    task.payment_tx_hash || task.paymentTxHash || task.escrow_address || task.escrowAddress ||
    ['funded', 'escrowed', 'paid', 'locked'].includes(String(task.payment_status ?? task.paymentStatus ?? task.funding_status ?? task.fundingStatus ?? '').toLowerCase())
  );
}

const responses = [];
const unique = new Map();
const arrayShapes = [];
for (const route of ROUTES) {
  const response = await get(route);
  const arrays = collectArrays(response.payload);
  const taskArrays = arrays.filter(entry => entry.items.some(looksLikeTask));
  for (const entry of taskArrays) {
    arrayShapes.push({route, path: entry.path, count: entry.items.length});
    for (const item of entry.items.filter(looksLikeTask)) {
      const task = compactTask(item);
      if (task.id) unique.set(String(task.id), task);
    }
  }
  responses.push({
    route,
    ok: response.ok,
    status: response.status,
    finalUrl: response.finalUrl,
    topLevelKeys: response.payload && typeof response.payload === 'object' && !Array.isArray(response.payload) ? Object.keys(response.payload) : [],
    arrayShapes: taskArrays.map(entry => ({path: entry.path, count: entry.items.length})),
    payloadPreview: taskArrays.length ? undefined : response.payload,
  });
}

const tasks = [...unique.values()].map(task => ({
  ...task,
  age_days: freshness(task.created_at),
  funding_evidence: fundingEvidence(task),
}));
tasks.sort((a, b) => {
  const funding = Number(b.funding_evidence) - Number(a.funding_evidence);
  if (funding) return funding;
  const dateA = Date.parse(a.created_at ?? '') || 0;
  const dateB = Date.parse(b.created_at ?? '') || 0;
  return dateB - dateA;
});

const funded = tasks.filter(task => task.funding_evidence);
const recent = tasks.filter(task => Number.isFinite(task.age_days) && task.age_days <= 30);
const unassigned = tasks.filter(task => !task.assigned_bot_id && ['open', 'active', ''].includes(String(task.status ?? '').toLowerCase()));

const detailProbes = [];
for (const task of [...funded, ...recent, ...unassigned].slice(0, 10)) {
  const routes = [`/api/tasks/${encodeURIComponent(task.id)}`, `/api/tasks/${encodeURIComponent(task.id)}/details`];
  for (const route of routes) {
    const response = await get(route);
    detailProbes.push({
      taskId: task.id,
      route,
      ok: response.ok,
      status: response.status,
      finalUrl: response.finalUrl,
      payload: response.ok ? response.payload : undefined,
    });
    if (response.ok) break;
  }
}

const report = {
  generatedAt: new Date().toISOString(),
  writesPerformed: [],
  responses,
  arrayShapes,
  uniqueTaskCount: tasks.length,
  fundedTaskCount: funded.length,
  recentTaskCount: recent.length,
  unassignedOpenTaskCount: unassigned.length,
  fundedTasks: funded.slice(0, 50),
  recentTasks: recent.slice(0, 50),
  bestUnassignedTasks: unassigned.slice(0, 80),
  detailProbes,
};

await mkdir(path.dirname(OUTPUT), {recursive: true});
const temporary = `${OUTPUT}.tmp`;
await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`, {mode: 0o600});
await rename(temporary, OUTPUT);
console.log(JSON.stringify({ok: true, tasks: tasks.length, funded: funded.length, recent: recent.length, unassigned: unassigned.length}));
