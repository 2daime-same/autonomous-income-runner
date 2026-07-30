import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const OUTPUT = process.env.AGENTJOB_POSTS_OUTPUT ?? 'market-output/agentjob-posts.json';
const ENDPOINT = 'https://agent-job.ai/api/mcp';
const BUYER_SIGNALS = /\b(need|looking for|seeking|wanted|can someone|who can|please help|help me|will pay|paying|bounty|commission|request|task for|job for|hire)\b/i;
const SELLER_SIGNALS = /\b(available for|online for|best fit|send (?:a|the|public)|i (?:will )?return|i offer|my service|entry price|paid reply|start a chat|delivery includes|available now)\b/i;

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

const client = new Client({name: 'boundaryledger-demand-probe', version: '1.1.0'});
const report = {generated_at: new Date().toISOString(), endpoint: ENDPOINT, mutating_calls: []};
try {
  await client.connect(new StreamableHTTPClientTransport(new URL(ENDPOINT)));
  const recent = parse(await client.callTool({name: 'list_posts', arguments: {sort: 'recent', page: 1, limit: 50}}));
  const hot = parse(await client.callTool({name: 'list_posts', arguments: {sort: 'hot', page: 1, limit: 50}}));
  report.recent = sanitize(recent);
  report.hot = sanitize(hot);
  const posts = [];
  for (const source of [recent, hot]) {
    const items = Array.isArray(source) ? source : Array.isArray(source?.posts) ? source.posts : [];
    for (const post of items) {
      if (post?.id && !posts.some(existing => existing.id === post.id)) posts.push(post);
    }
  }
  report.unique_post_count = posts.length;
  const classified = posts.map(post => {
    const text = `${post?.title ?? ''}\n${post?.body ?? ''}`;
    return {
      post,
      buyer_signal: BUYER_SIGNALS.test(text),
      seller_signal: SELLER_SIGNALS.test(text),
    };
  });
  report.buyer_demand_candidates = classified
    .filter(item => item.buyer_signal && !item.seller_signal)
    .slice(0, 30)
    .map(item => sanitize(item.post));
  report.seller_offer_count = classified.filter(item => item.seller_signal).length;
  report.ambiguous_demand_candidates = classified
    .filter(item => item.buyer_signal && item.seller_signal)
    .slice(0, 20)
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
