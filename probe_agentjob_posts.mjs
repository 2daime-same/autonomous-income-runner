import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const OUTPUT = process.env.AGENTJOB_POSTS_OUTPUT ?? 'market-output/agentjob-posts.json';
const ENDPOINT = 'https://agent-job.ai/api/mcp';
const BUYER_SIGNALS = /\b(need|looking for|seeking|wanted|can someone|who can|please help|help me|will pay|paying|bounty|commission|request|task for|job for|hire|求|募集|依頼|お願い|助けて)\b/i;
const SELLER_SIGNALS = /\b(available for|online for|best fit|send (?:a|the|public)|i (?:will )?return|i offer|my service|entry price|paid reply|start a chat|delivery includes|available now|対応します|提供します|受付中)\b/i;
const PAGE_DELAY_MS = 61_000;

function parse(result) {
  const text = result?.content?.find(item => item?.type === 'text' && typeof item.text === 'string')?.text;
  if (!text) return null;
  try { return JSON.parse(text); } catch { return {text}; }
}

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      output[key] = /token|secret|api.?key|authorization|private|credential|otp|email/i.test(key)
        ? '[REDACTED]'
        : sanitize(item);
    }
    return output;
  }
  if (typeof value === 'string') return value.replace(/\b(?:ak|aj|agentjob)_[A-Za-z0-9_-]{8,}/gi, '[REDACTED]');
  return value;
}

function unwrapPosts(source) {
  return Array.isArray(source) ? source : Array.isArray(source?.posts) ? source.posts : [];
}

const client = new Client({name: 'boundaryledger-demand-probe', version: '1.2.0'});
const report = {
  generated_at: new Date().toISOString(),
  endpoint: ENDPOINT,
  mutating_calls: [],
  rate_policy: {minimum_delay_ms_between_feed_calls: PAGE_DELAY_MS},
  pages: [],
};
try {
  await client.connect(new StreamableHTTPClientTransport(new URL(ENDPOINT)));
  const sources = [];
  const queries = [
    {sort: 'recent', page: 1, limit: 50},
    {sort: 'recent', page: 2, limit: 50},
    {sort: 'recent', page: 3, limit: 50},
    {sort: 'hot', page: 1, limit: 50},
  ];
  for (let index = 0; index < queries.length; index += 1) {
    if (index > 0) await new Promise(resolve => setTimeout(resolve, PAGE_DELAY_MS));
    const query = queries[index];
    const value = parse(await client.callTool({name: 'list_posts', arguments: query}));
    sources.push(value);
    report.pages.push({query, count: unwrapPosts(value).length, value: sanitize(value)});
  }

  const posts = [];
  for (const source of sources) {
    for (const post of unwrapPosts(source)) {
      if (post?.id && !posts.some(existing => existing.id === post.id)) posts.push(post);
    }
  }
  report.unique_post_count = posts.length;
  const classified = posts.map(post => {
    const text = `${post?.title ?? ''}\n${post?.body ?? ''}`;
    return {post, buyer_signal: BUYER_SIGNALS.test(text), seller_signal: SELLER_SIGNALS.test(text)};
  });
  report.buyer_demand_candidates = classified
    .filter(item => item.buyer_signal && !item.seller_signal)
    .slice(0, 100)
    .map(item => sanitize(item.post));
  report.seller_offer_count = classified.filter(item => item.seller_signal).length;
  report.ambiguous_demand_candidates = classified
    .filter(item => item.buyer_signal && item.seller_signal)
    .slice(0, 50)
    .map(item => sanitize(item.post));
  report.ok = true;
} catch (error) {
  report.ok = false;
  report.error = sanitize(error.message);
  process.exitCode = 1;
} finally {
  try { await client.close(); } catch {}
  await mkdir(path.dirname(OUTPUT), {recursive: true});
  const temp = `${OUTPUT}.tmp`;
  await writeFile(temp, `${JSON.stringify(report, null, 2)}\n`, {mode: 0o600});
  await rename(temp, OUTPUT);
}
