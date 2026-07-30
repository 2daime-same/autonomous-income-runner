import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const ENDPOINT = 'https://agent-job.ai/api/mcp';
const OUTPUT = process.env.AGENTJOB_DEEP_OUTPUT ?? 'market-output/agentjob-deep-demand.json';
const MAX_PAGES = Math.min(30, Math.max(2, Number(process.env.AGENTJOB_DEEP_PAGES ?? '20')));
const BUYER = /\b(need|needed|looking for|seeking|wanted|can someone|who can|please help|help me|could someone|will pay|paying|bounty|commission|request|task for|job for|hire|fix my|build me|write me|generate me|create me)\b/i;
const SELLER = /\b(available for|online for|best fit|send (?:a|the|public)|i (?:will|can) (?:return|deliver|provide)|i offer|my service|entry price|paid reply|start a chat|delivery includes|available now|hire me|i am available)\b/i;
const RISK = /\b(private key|seed phrase|credential|password|account takeover|exploit|hack|bypass|fake engagement|spam|phishing|malware|steal|dox|adult|porn)\b/i;

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

function items(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.posts)) return value.posts;
  if (Array.isArray(value?.data)) return value.data;
  return [];
}

const client = new Client({name: 'boundaryledger-deep-demand-probe', version: '1.0.0'});
const report = {
  generated_at: new Date().toISOString(),
  endpoint: ENDPOINT,
  pages_requested: MAX_PAGES,
  calls_performed: [],
  mutating_calls: [],
};

try {
  await client.connect(new StreamableHTTPClientTransport(new URL(ENDPOINT)));
  const unique = new Map();
  for (const sort of ['recent', 'hot']) {
    for (let page = 1; page <= MAX_PAGES; page += 1) {
      const parsed = parse(await client.callTool({name: 'list_posts', arguments: {sort, page, limit: 50}}));
      report.calls_performed.push({tool: 'list_posts', sort, page});
      const batch = items(parsed);
      for (const post of batch) {
        if (post?.id && !unique.has(post.id)) unique.set(post.id, post);
      }
      if (batch.length < 50) break;
    }
  }

  const candidates = [];
  for (const post of unique.values()) {
    const text = `${post?.title ?? ''}\n${post?.body ?? ''}`;
    if (!BUYER.test(text) || SELLER.test(text) || RISK.test(text)) continue;
    const created = Date.parse(post?.createdAt ?? post?.created_at ?? '');
    candidates.push({
      id: post.id,
      authorId: post.authorId ?? post.author_id ?? null,
      title: String(post?.title ?? '').slice(0, 300),
      body: String(post?.body ?? '').slice(0, 4000),
      replyCount: post?.replyCount ?? post?.reply_count ?? null,
      bestReplyId: post?.bestReplyId ?? post?.best_reply_id ?? null,
      createdAt: post?.createdAt ?? post?.created_at ?? null,
      age_days: Number.isFinite(created) ? Math.floor((Date.now() - created) / 86400000) : null,
    });
  }
  candidates.sort((a, b) => Date.parse(b.createdAt ?? 0) - Date.parse(a.createdAt ?? 0));
  report.unique_post_count = unique.size;
  report.buyer_candidate_count = candidates.length;
  report.buyer_candidates = sanitize(candidates.slice(0, 100));
  report.ok = true;
} catch (error) {
  report.ok = false;
  report.error = sanitize(`${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`);
  process.exitCode = 1;
} finally {
  try { await client.close(); } catch {}
  await mkdir(path.dirname(OUTPUT), {recursive: true});
  const temporary = `${OUTPUT}.tmp`;
  await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`, {mode: 0o600});
  await rename(temporary, OUTPUT);
  console.log(JSON.stringify({ok: report.ok, posts: report.unique_post_count ?? 0, buyers: report.buyer_candidate_count ?? 0}));
}
