#!/usr/bin/env node
/** Read-only Algora bounty inventory probe using Algora's public SDK. */
import fs from 'node:fs';
import path from 'node:path';
import { algora } from '@algora/sdk';

const output = process.env.ALGORA_OUTPUT_FILE || 'market-output/algora.json';
const maxPages = 20;
const pageSize = 100;

function rewardUsd(reward) {
  if (!reward || typeof reward.amount !== 'number') return 0;
  return reward.amount / 100;
}

function simplify(item) {
  const task = item?.task || {};
  const org = item?.org || {};
  return {
    id: item?.id ?? null,
    title: task.title ?? null,
    body: typeof task.body === 'string' ? task.body.slice(0, 12000) : null,
    url: task.url ?? null,
    status: task.status ?? null,
    repo_name: task.repo_name ?? null,
    issue_number: task.number ?? task.issue_number ?? null,
    org_handle: org.handle ?? null,
    org_name: org.display_name ?? null,
    org_avatar_url: org.avatar_url ?? null,
    tech: item?.tech ?? task.tech ?? [],
    reward_usd: rewardUsd(item?.reward),
    reward_formatted: item?.reward_formatted ?? null,
    created_at: task.created_at ?? item?.created_at ?? null,
    updated_at: task.updated_at ?? item?.updated_at ?? null,
    solver_count: Array.isArray(item?.solvers) ? item.solvers.length : null,
    raw_keys: Object.keys(item || {}).sort(),
  };
}

async function fetchVariant(name, rewarded) {
  const rawItems = [];
  let cursor;
  let error = null;
  try {
    for (let page = 0; page < maxPages; page += 1) {
      const params = { status: 'active', limit: pageSize };
      if (typeof rewarded === 'boolean') params.rewarded = rewarded;
      if (cursor) params.cursor = cursor;
      const result = await algora.bounty.list.query(params);
      const pageItems = Array.isArray(result?.items) ? result.items : [];
      rawItems.push(...pageItems);
      cursor = result?.next_cursor || null;
      if (!cursor || pageItems.length === 0) break;
    }
  } catch (caught) {
    error = `${caught?.name || 'Error'}: ${caught?.message || String(caught)}`;
  }
  return {
    name,
    rewarded_filter: typeof rewarded === 'boolean' ? rewarded : null,
    raw_count: rawItems.length,
    error,
    items: rawItems.map(simplify),
  };
}

const variants = [
  await fetchVariant('active_without_rewarded_filter', undefined),
  await fetchVariant('active_unrewarded', false),
  await fetchVariant('active_rewarded', true),
];

const deduped = new Map();
for (const variant of variants) {
  for (const item of variant.items) {
    const key = item.url || item.id || JSON.stringify([item.org_handle, item.repo_name, item.issue_number, item.title]);
    if (!deduped.has(key)) deduped.set(key, item);
  }
}

const activeWithMoney = [...deduped.values()]
  .filter((item) => item.reward_usd > 0 && item.url)
  .sort((a, b) => {
    const rewardDifference = a.reward_usd - b.reward_usd;
    if (rewardDifference !== 0) return rewardDifference;
    return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
  });

const report = {
  generated_at: new Date().toISOString(),
  source: 'Algora public SDK @algora/sdk',
  status_filter: 'active',
  query_variants: variants.map((variant) => ({
    name: variant.name,
    rewarded_filter: variant.rewarded_filter,
    raw_count: variant.raw_count,
    error: variant.error,
  })),
  unique_active_items: deduped.size,
  total_active_with_money: activeWithMoney.length,
  total_value_usd: activeWithMoney.reduce((sum, item) => sum + item.reward_usd, 0),
  items: activeWithMoney,
};

fs.mkdirSync(path.dirname(output), { recursive: true });
const temp = `${output}.tmp`;
fs.writeFileSync(temp, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
fs.renameSync(temp, output);
console.log(JSON.stringify({ ok: true, output, count: activeWithMoney.length, variants: report.query_variants }));
