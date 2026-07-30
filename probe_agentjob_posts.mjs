import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const OUTPUT = process.env.AGENTJOB_POSTS_OUTPUT ?? 'market-output/agentjob-posts.json';
const ENDPOINT = 'https://agent-job.ai/api/mcp';

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

const client = new Client({name: 'boundaryledger-demand-probe', version: '1.0.0'});
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
  report.demand_candidates = posts
    .filter(post => /\b(hire|paid|pay|bounty|need|looking for|help with|commission|task|job|research|code review|debug|data)\b/i.test(`${post?.title ?? ''} ${post?.body ?? ''}`))
    .slice(0, 30)
    .map(post => sanitize(post));
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
