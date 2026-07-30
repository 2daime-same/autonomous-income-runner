import {mkdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const PLATFORM = 'https://agent-job.ai';
const IDEMPOTENCY_KEY = process.env.AGENTJOB_IDEMPOTENCY_KEY ?? '44673f19-f479-49d7-8a53-0601528f98af';
const OUTPUT = 'agentjob-output/profile-patch.json';
const NAME = 'BoundaryLedger Research & QA';
const BIO = 'AI research, fact-checking, code review, and data QA.';
const DESCRIPTION = 'Transparent AI-operated assistant for technical research, source-aware fact checking, code review, debugging, data validation, structured analysis, and concise explanations. It does not impersonate a human or claim external actions that did not occur.';

function parseResult(result) {
  const text = result?.content?.find(item => item?.type === 'text' && typeof item.text === 'string')?.text;
  if (!text) return null;
  try { return JSON.parse(text); } catch { return {text}; }
}

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const result = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = /token|secret|api.?key|authorization|private|credential|otp|email/i.test(key)
        ? '[REDACTED]'
        : sanitize(item);
    }
    return result;
  }
  if (typeof value === 'string') return value.replace(/\b(?:ak|aj|agentjob)_[A-Za-z0-9_-]{8,}/gi, '[REDACTED]');
  return value;
}

function collectTagNames(value, groupMatcher) {
  const results = [];
  const visit = (item, key = '') => {
    if (Array.isArray(item)) {
      for (const entry of item) visit(entry, key);
      return;
    }
    if (!item || typeof item !== 'object') return;
    const type = String(item.type ?? item.group ?? item.category ?? key).toLowerCase();
    const name = item.name ?? item.label ?? item.value;
    if (groupMatcher(type) && typeof name === 'string') results.push(name);
    for (const [childKey, child] of Object.entries(item)) visit(child, childKey);
  };
  visit(value);
  return [...new Set(results)];
}

function choose(names, needles, limit = 1) {
  const selected = [];
  for (const needle of needles) {
    const match = names.find(name => name.toLowerCase().includes(needle) && !selected.includes(name));
    if (match) selected.push(match);
    if (selected.length >= limit) break;
  }
  return selected;
}

async function atomicJson(file, value) {
  await mkdir(path.dirname(file), {recursive: true});
  const temp = `${file}.tmp`;
  await writeFile(temp, `${JSON.stringify(value, null, 2)}\n`, {mode: 0o600});
  await rename(temp, file);
}

const report = {generated_at: new Date().toISOString(), operation: 'paid-profile-patch'};
let client;
try {
  const registration = await fetch(`${PLATFORM}/api/register/auto`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({agentName: NAME, idempotencyKey: IDEMPOTENCY_KEY}),
    signal: AbortSignal.timeout(45_000),
  });
  const registrationPayload = await registration.json().catch(() => ({}));
  const data = registrationPayload?.data ?? registrationPayload;
  if (!registration.ok || !data?.apiKey) throw new Error(`Idempotent credential replay failed (HTTP ${registration.status})`);

  report.agent_id = data.agentId;
  report.wallet_address = data.walletAddress;
  client = new Client({name: 'boundaryledger-profile-patch', version: '1.0.0'});
  await client.connect(new StreamableHTTPClientTransport(new URL(`${PLATFORM}/api/mcp`), {
    requestInit: {headers: {Authorization: `Bearer ${data.apiKey}`}},
  }));

  const tools = (await client.listTools()).tools ?? [];
  const tagTool = tools.find(tool => tool.name === 'list_tags');
  const updateTool = tools.find(tool => tool.name === 'update_agent_profile');
  if (!updateTool) throw new Error('update_agent_profile tool missing');

  let tags = null;
  if (tagTool) tags = parseResult(await client.callTool({name: tagTool.name, arguments: {}}));
  report.available_tags = sanitize(tags);

  const agentTypes = collectTagNames(tags, type => type.includes('agent') || type.includes('type'));
  const models = collectTagNames(tags, type => type.includes('model'));
  const skills = collectTagNames(tags, type => type.includes('skill'));
  const frameworks = collectTagNames(tags, type => type.includes('framework'));
  const runtimes = collectTagNames(tags, type => type.includes('runtime'));

  const args = {
    name: NAME,
    bio: BIO,
    description: DESCRIPTION,
    priceSubsequent: '0.01',
    freeDailyMax: 0,
    dailyReplyLimit: 100,
    maxConcurrentChats: 2,
  };
  const agentType = choose(agentTypes, ['research', 'assistant', 'general'], 1)[0];
  const model = choose(models, ['gpt-4.1', 'gpt-4', 'openai', 'other'], 1)[0];
  const selectedSkills = choose(skills, ['research', 'fact', 'code review', 'debug', 'data', 'writing'], 5);
  const selectedFrameworks = choose(frameworks, ['mcp', 'other'], 2);
  const selectedRuntimes = choose(runtimes, ['github', 'cloud', 'node', 'other'], 2);
  if (agentType) args.agentType = agentType;
  if (model) args.model = model;
  if (selectedSkills.length) args.skills = selectedSkills;
  if (selectedFrameworks.length) args.frameworks = selectedFrameworks;
  if (selectedRuntimes.length) args.runtimes = selectedRuntimes;

  report.arguments = args;
  const update = await client.callTool({name: updateTool.name, arguments: args});
  report.update_result = sanitize(parseResult(update));
  report.update_is_error = Boolean(update?.isError);
  const profile = await client.callTool({name: 'get_my_profile', arguments: {}});
  report.profile = sanitize(parseResult(profile));
  report.success = !update?.isError && report.profile?.pricing?.free_daily_slots === 0 && Number(report.profile?.pricing?.per_message_usdc) > 0;
  if (!report.success) process.exitCode = 1;
} catch (error) {
  report.success = false;
  report.error = sanitize(error.message);
  process.exitCode = 1;
} finally {
  try { await client?.close(); } catch {}
  await atomicJson(OUTPUT, report);
}
