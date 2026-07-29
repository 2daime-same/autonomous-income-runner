#!/usr/bin/env node
/** Read-only Algora bounty inventory probe using Algora's public SDK. */
import fs from 'node:fs';
import path from 'node:path';
import { algora } from '@algora/sdk';

const output = process.env.ALGORA_OUTPUT_FILE || 'market-output/algora.json';
const maxPages = 10;
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
    body: typeof task.body === 'string' ? task.body.slice(0, 5000) : null,
    url: task.url ?? null,
    status: task.status ?? null,
    repo_name: task.repo_name ?? null,
    org_handle: org.handle ?? null,
    org_name: org.display_name ?? null,
    tech: item?.tech ?? task.tech ?? [],
    reward_usd: rewardUsd(item?.reward),
    reward_formatted: item?.reward_formatted ?? null,
    created_at: task.created_at ?? item?.created_at ?? null,
    updated_at: task.updated_at ?? item?.updated_at ?? null,
    raw_keys: Object.keys(item || {}).sort(),
  };
}

const items = [];
let cursor;
for (let page = 0; page < maxPages; page += 1) {
  const params = { status: 'active', rewarded: true, limit: pageSize };
  if (cursor) params.cursor = cursor;
  const result = await algora.bounty.list.query(params);
  const pageItems = Array.isArray(result?.items) ? result.items : [];
  items.push(...pageItems.map(simplify));
  cursor = result?.next_cursor || null;
  if (!cursor || pageItems.length === 0) break;
}

const rewarded = items
  .filter((item) => item.reward_usd > 0 && item.url)
  .sort((a, b) => b.reward_usd - a.reward_usd);

const report = {
  generated_at: new Date().toISOString(),
  source: 'Algora public SDK @algora/sdk',
  status_filter: 'active',
  total_active_rewarded: rewarded.length,
  total_value_usd: rewarded.reduce((sum, item) => sum + item.reward_usd, 0),
  items: rewarded,
};

fs.mkdirSync(path.dirname(output), { recursive: true });
const temp = `${output}.tmp`;
fs.writeFileSync(temp, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
fs.renameSync(temp, output);
console.log(JSON.stringify({ ok: true, output, count: rewarded.length }));
