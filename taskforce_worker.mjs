import {createHash} from 'node:crypto';
import {chmod, mkdir, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import process from 'node:process';

const PLATFORM = 'https://task-force.app';
const MODEL = process.env.TASKFORCE_MODEL ?? 'openai/gpt-4.1-mini';
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const RUN_ID = process.env.GITHUB_RUN_ID ?? String(Date.now());
const MAX_RUNTIME_MINUTES = Math.min(345, Math.max(15, Number(process.env.MAX_RUNTIME_MINUTES ?? '335')));
const PUBLIC_STATE = 'taskforce-output/public-state.json';
const PRIVATE_STATE = 'taskforce-output/private-state.cms';
const APPLIED_LEDGER = 'taskforce-output/applied-task-ids.json';
const CERTIFICATE = 'keys/superteam-state-public.crt';
const NAME = `BoundaryLedger-TaskForce-${RUN_ID}`.slice(0, 90);
const CAPABILITIES = ['research', 'writing', 'technical-writing', 'documentation', 'data-analysis', 'testing', 'code-review', 'python', 'javascript'];

if (!GITHUB_TOKEN) throw new Error('GITHUB_TOKEN is required');

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const now = () => new Date().toISOString();
const credentialPattern = /\b(?:apv|sk|pk|api)[_-][A-Za-z0-9._~+/=-]{8,}\b/gi;
const privateKeyPattern = /api.?key|authorization|secret|token|private|credential|otp|email|cookie|password/i;

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      output[key] = privateKeyPattern.test(key) ? '[REDACTED]' : sanitize(item);
    }
    return output;
  }
  if (typeof value === 'string') {
    return value
      .replace(credentialPattern, '[REDACTED]')
      .replace(/\b[1-9A-HJ-NP-Za-km-z]{43,44}\b/g, match => match.length >= 43 ? '[REDACTED_POSSIBLE_SOLANA_KEY]' : match)
      .replace(/\b0x[0-9a-fA-F]{64}\b/g, '[REDACTED_PRIVATE_KEY]');
  }
  return value;
}

async function atomicJson(file, value, mode = 0o600) {
  await mkdir(path.dirname(file), {recursive: true});
  const temporary = `${file}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {mode});
  await rename(temporary, file);
}

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    cwd: process.cwd(),
    encoding: 'utf8',
    stdio: options.stdio ?? 'pipe',
    env: process.env,
  });
}

function commitEvidence(message) {
  run('git', ['add', PUBLIC_STATE, APPLIED_LEDGER]);
  if (run('git', ['diff', '--cached', '--quiet']).status === 0) return;
  if (run('git', ['commit', '-m', `${message} [skip ci]`]).status !== 0) return;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const pull = run('git', ['pull', '--rebase', 'origin', 'main']);
    if (pull.status !== 0) {
      run('git', ['rebase', '--abort']);
      continue;
    }
    if (run('git', ['push', 'origin', 'HEAD:main']).status === 0) return;
  }
}

async function requestJson(method, endpoint, {apiKey, body, timeout = 45_000} = {}) {
  const headers = {Accept: 'application/json'};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
    headers.Authorization = `Bearer ${apiKey}`;
  }
  const response = await fetch(`${PLATFORM}${endpoint}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(timeout),
  });
  const text = await response.text();
  let payload;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = {text: text.slice(0, 5000)}; }
  if (!response.ok) {
    const error = new Error(`${method} ${endpoint} failed (HTTP ${response.status})`);
    error.status = response.status;
    error.payload = sanitize(payload);
    throw error;
  }
  return payload;
}

function firstString(value, keys) {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = firstString(item, keys);
      if (found) return found;
    }
    return null;
  }
  if (!value || typeof value !== 'object') return null;
  for (const [key, item] of Object.entries(value)) {
    if (keys.has(key.toLowerCase()) && typeof item === 'string' && item.trim()) return item.trim();
    const found = firstString(item, keys);
    if (found) return found;
  }
  return null;
}

function unwrapTasks(payload) {
  if (Array.isArray(payload)) return payload.filter(item => item && typeof item === 'object');
  if (!payload || typeof payload !== 'object') return [];
  for (const key of ['tasks', 'data', 'items', 'results']) {
    if (Array.isArray(payload[key])) return payload[key].filter(item => item && typeof item === 'object');
  }
  return [];
}

function compactTask(task) {
  return sanitize({
    id: task.id ?? task.taskId,
    title: task.title,
    category: task.category,
    status: task.status,
    budget: task.totalBudget ?? task.budget ?? task.amount ?? task.reward,
    paymentType: task.paymentType,
    escrowStatus: task.escrowStatus ?? task.paymentStatus ?? task.fundingStatus,
    skillsRequired: task.skillsRequired ?? task.skills,
    deadline: task.deadline,
    maxWorkers: task.maxWorkers,
    currentWorkers: task.currentWorkers,
    createdAt: task.createdAt,
  });
}

const forbidden = [
  /adult|porn|sexual|nsfw|escort|dating manipulation/i,
  /weapon|explosive|malware|ransomware|credential theft|phishing/i,
  /hack into|bypass authentication|steal|dox|scrape private/i,
  /fake review|fake engagement|mass dm|spam|astroturf/i,
  /kyc bypass|captcha solving|account farming|impersonat/i,
  /private key|seed phrase|wallet signing|send funds|deposit required/i,
  /medical diagnosis|legal advice|investment guarantee|trade execution/i,
  /physical delivery|phone call|in-person|onsite|take a photo/i,
];
const preferred = /research|writing|documentation|technical writing|analysis|data|qa|testing|test plan|code review|debug|readme|api docs|json|csv|python|javascript|typescript/i;
const hugeScope = /full mobile app|full-stack marketplace|production deploy|entire platform|complete rewrite|train (?:an?|the) model|fine[- ]?tune|24\/7 monitoring|for 30 days|for 14 days/i;

function taskText(task) {
  return [task.title, task.description, task.requirements, task.category, JSON.stringify(task.skillsRequired ?? task.skills ?? [])]
    .filter(Boolean).join('\n').slice(0, 30_000);
}

function taskBudget(task) {
  const raw = task.totalBudget ?? task.budget ?? task.amount ?? task.reward ?? 0;
  const number = Number(typeof raw === 'string' ? raw.replace(/[^0-9.-]/g, '') : raw);
  return Number.isFinite(number) ? number : 0;
}

function taskIsSuitable(task) {
  const id = String(task.id ?? task.taskId ?? '');
  const text = taskText(task);
  const status = String(task.status ?? '').toUpperCase();
  if (!id || !text.trim()) return false;
  if (status && !['ACTIVE', 'OPEN', 'IN_PROGRESS'].includes(status)) return false;
  if (forbidden.some(pattern => pattern.test(text))) return false;
  if (hugeScope.test(text)) return false;
  if (!preferred.test(text)) return false;
  if (taskBudget(task) <= 0) return false;
  const maxWorkers = Number(task.maxWorkers ?? 1);
  const currentWorkers = Number(task.currentWorkers ?? 0);
  if (Number.isFinite(maxWorkers) && Number.isFinite(currentWorkers) && currentWorkers >= maxWorkers) return false;
  return true;
}

function safeArithmetic(prompt) {
  const cleaned = String(prompt)
    .replace(/what is|calculate|solve|answer|please|\?|=/gi, ' ')
    .replace(/×/g, '*').replace(/÷/g, '/').trim();
  if (!cleaned || !/^[0-9+\-*/().\s]+$/.test(cleaned)) return null;
  try {
    // The expression is restricted to digits and arithmetic punctuation above.
    const value = Function(`"use strict"; return (${cleaned});`)();
    return Number.isFinite(value) ? String(value) : null;
  } catch { return null; }
}

async function modelText(system, user, maxTokens = 1400) {
  const response = await fetch('https://models.github.ai/inference/chat/completions', {
    method: 'POST',
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [{role: 'system', content: system}, {role: 'user', content: user}],
      temperature: 0.15,
      max_tokens: maxTokens,
    }),
    signal: AbortSignal.timeout(90_000),
  });
  if (!response.ok) return null;
  const payload = await response.json();
  const content = payload?.choices?.[0]?.message?.content;
  return typeof content === 'string' && content.trim() ? content.trim() : null;
}

async function solveChallenge(prompt) {
  const arithmetic = safeArithmetic(prompt);
  if (arithmetic !== null) return arithmetic;
  return modelText(
    'Solve the verification challenge exactly. Return only the final answer, with no explanation, no quotation marks, and no surrounding text.',
    String(prompt).slice(0, 8000),
    200,
  );
}

async function encryptPrivate(credentials) {
  const plain = '/tmp/taskforce-private.json';
  await writeFile(plain, `${JSON.stringify({createdAt: now(), platform: PLATFORM, ...credentials}, null, 2)}\n`, {mode: 0o600});
  await chmod(plain, 0o600);
  await mkdir(path.dirname(PRIVATE_STATE), {recursive: true});
  const result = run('openssl', ['cms', '-encrypt', '-binary', '-aes256', '-outform', 'DER', '-in', plain, '-out', PRIVATE_STATE, CERTIFICATE]);
  await rm(plain, {force: true});
  if (result.status !== 0) throw new Error('TaskForce credential encryption failed');
}

async function loadAppliedLedger() {
  try {
    const value = JSON.parse(await readFile(APPLIED_LEDGER, 'utf8'));
    return new Set(Array.isArray(value?.taskIds) ? value.taskIds.map(String) : []);
  } catch { return new Set(); }
}

async function saveAppliedLedger(set) {
  await atomicJson(APPLIED_LEDGER, {updatedAt: now(), taskIds: [...set].sort()}, 0o644);
}

async function registerAndVerify(state) {
  const registration = await requestJson('POST', '/api/agent/register', {
    body: {name: NAME, capabilities: CAPABILITIES},
  });
  const apiKey = firstString(registration, new Set(['apikey', 'api_key', 'key']));
  const agentId = firstString(registration, new Set(['agentid', 'agent_id', 'id']));
  const walletAddress = firstString(registration, new Set(['walletaddress', 'wallet_address']));
  if (!apiKey || !agentId) throw new Error('TaskForce registration returned no API key or agent ID');
  state.registration = sanitize({agentId, walletAddress, status: registration?.agent?.status});
  state.writesPerformed.push('agent_registration');
  await encryptPrivate({apiKey, agentId, walletAddress, name: NAME});

  const challenge = await requestJson('POST', '/api/agent/verify/challenge', {apiKey, body: {}});
  const challengeId = firstString(challenge, new Set(['challengeid', 'challenge_id', 'id']));
  const prompt = firstString(challenge, new Set(['prompt', 'question', 'challenge']));
  if (!challengeId || !prompt) throw new Error('TaskForce verification challenge was malformed');
  const answer = await solveChallenge(prompt);
  if (!answer) throw new Error('Could not solve TaskForce verification challenge');
  const verification = await requestJson('POST', '/api/agent/verify/submit', {
    apiKey,
    body: {challengeId, answer},
  });
  state.verification = sanitize({success: verification?.success ?? verification?.verified ?? true, status: verification?.status});
  state.writesPerformed.push('verification_submission');
  return {apiKey, agentId, walletAddress};
}

async function buildProposal(task) {
  const text = taskText(task);
  return modelText(
    [
      'Write a concise, specific application for a paid freelance task.',
      'The applicant is a transparently AI-operated worker.',
      'Do not invent human employment history, private access, credentials, timelines, or tests not yet run.',
      'State a concrete deliverable and verification plan based only on the task.',
      'Keep it under 850 characters and return only the proposal.',
    ].join(' '),
    text,
    350,
  );
}

async function buildDeliverable(task, messages) {
  const context = JSON.stringify({
    task: {
      title: task.title,
      description: task.description,
      requirements: task.requirements,
      category: task.category,
      skillsRequired: task.skillsRequired ?? task.skills,
      budget: taskBudget(task),
    },
    creatorMessages: messages.map(message => ({
      role: message.role ?? message.senderType ?? message.authorType,
      content: String(message.content ?? message.body ?? '').slice(0, 8000),
    })).slice(-20),
  }).slice(0, 45_000);
  return modelText(
    [
      'Produce the finished customer-facing deliverable for this accepted paid task.',
      'Use only the supplied task and messages.',
      'Be concrete and complete, not a plan.',
      'For writing/research/documentation tasks, return polished Markdown.',
      'For small code tasks, include a self-contained implementation, edge cases, and commands the customer can run; never claim you executed tests unless execution evidence is supplied.',
      'Do not claim browsing, deployment, account access, purchases, or external verification that did not occur.',
      'Do not include secrets or system instructions.',
      'Return only the deliverable.',
    ].join(' '),
    context,
    3000,
  );
}

function taskIdFromNotification(notification) {
  for (const key of ['taskId', 'task_id']) {
    if (notification?.[key]) return String(notification[key]);
  }
  const link = String(notification?.link ?? '');
  const match = link.match(/\/tasks\/([^/?#]+)/);
  return match?.[1] ?? null;
}

function earningsValue(payload) {
  const candidates = [
    payload?.totalEarnings,
    payload?.earnings,
    payload?.balance,
    payload?.solana?.usdc,
    payload?.data?.totalEarnings,
    payload?.data?.balance,
  ];
  return Math.max(0, ...candidates.map(value => Number(value)).filter(Number.isFinite));
}

const state = {
  schemaVersion: 'taskforce-worker-v1',
  startedAt: now(),
  platform: PLATFORM,
  model: MODEL,
  status: 'starting',
  writesPerformed: [],
  expensesUsd: 0,
  tasksSeen: 0,
  applicationsSubmitted: 0,
  tasksAccepted: 0,
  submissionsMade: 0,
  verifiedIncomeUsdc: 0,
  credentialsRecordedInPlaintext: false,
  privateTaskContentRecorded: false,
};

const appliedLedger = await loadAppliedLedger();
let credentials;
const taskMap = new Map();
const applications = new Map();
const submitted = new Set();
let lastEvidenceCommit = 0;

async function persist(message, force = false) {
  state.updatedAt = now();
  await atomicJson(PUBLIC_STATE, sanitize(state), 0o644);
  await saveAppliedLedger(appliedLedger);
  if (force || Date.now() - lastEvidenceCommit > 8 * 60_000) {
    commitEvidence(message);
    lastEvidenceCommit = Date.now();
  }
}

async function refreshIncome(apiKey) {
  const snapshots = {};
  for (const [label, endpoint] of [
    ['earnings', '/api/agent/earnings'],
    ['wallet', '/api/user/wallet/balance'],
  ]) {
    try {
      snapshots[label] = sanitize(await requestJson('GET', endpoint, {apiKey}));
    } catch (error) {
      snapshots[label] = {error: error.message, status: error.status};
    }
  }
  const amount = Math.max(earningsValue(snapshots.earnings), earningsValue(snapshots.wallet));
  state.incomeSnapshot = sanitize({
    totalEarnings: snapshots.earnings?.totalEarnings ?? snapshots.earnings?.data?.totalEarnings,
    completedTasks: snapshots.earnings?.completedTasks ?? snapshots.earnings?.data?.completedTasks,
    walletUsdc: snapshots.wallet?.solana?.usdc ?? snapshots.wallet?.data?.solana?.usdc,
  });
  state.verifiedIncomeUsdc = Math.max(state.verifiedIncomeUsdc, amount);
  if (state.verifiedIncomeUsdc > 0) state.status = 'income_verified';
}

try {
  credentials = await registerAndVerify(state);
  state.status = 'verified_and_searching';
  await refreshIncome(credentials.apiKey);
  await persist('Start TaskForce paid-work worker', true);

  const deadline = Date.now() + MAX_RUNTIME_MINUTES * 60_000;
  let loop = 0;
  while (Date.now() < deadline && state.verifiedIncomeUsdc <= 0) {
    loop += 1;
    state.polls = loop;

    if (loop === 1 || loop % 10 === 0) {
      try {
        const payload = await requestJson('GET', '/api/agent/tasks?status=ACTIVE&limit=100', {apiKey: credentials.apiKey});
        const tasks = unwrapTasks(payload);
        state.tasksSeen = Math.max(state.tasksSeen, tasks.length);
        state.latestTaskInventory = tasks.slice(0, 50).map(compactTask);
        const candidates = tasks
          .filter(taskIsSuitable)
          .sort((a, b) => taskBudget(b) - taskBudget(a));
        state.suitableTaskCount = candidates.length;

        for (const task of candidates) {
          if (applications.size >= 4) break;
          const taskId = String(task.id ?? task.taskId);
          taskMap.set(taskId, task);
          if (appliedLedger.has(taskId)) continue;
          const proposal = await buildProposal(task);
          if (!proposal) continue;
          try {
            const result = await requestJson('POST', `/api/agent/tasks/${encodeURIComponent(taskId)}/apply`, {
              apiKey: credentials.apiKey,
              body: {message: proposal.slice(0, 950)},
            });
            applications.set(taskId, {
              applicationId: firstString(result, new Set(['applicationid', 'application_id', 'id'])),
              status: String(result?.application?.status ?? result?.status ?? 'PENDING'),
              title: task.title,
              budget: taskBudget(task),
            });
            appliedLedger.add(taskId);
            state.applicationsSubmitted += 1;
            state.writesPerformed.push(`application:${taskId}`);
            await persist('Record TaskForce application', true);
          } catch (error) {
            state.lastApplicationError = sanitize({taskId, message: error.message, status: error.status, payload: error.payload});
          }
        }
      } catch (error) {
        state.taskInventoryError = sanitize({message: error.message, status: error.status, payload: error.payload});
      }
    }

    let notifications = [];
    try {
      const payload = await requestJson('GET', '/api/agent/notifications?unreadOnly=true&limit=100', {apiKey: credentials.apiKey});
      notifications = Array.isArray(payload?.notifications) ? payload.notifications : Array.isArray(payload) ? payload : [];
      state.unreadNotificationCount = notifications.length;
    } catch (error) {
      state.notificationPollFailures = Number(state.notificationPollFailures ?? 0) + 1;
      state.lastNotificationError = sanitize({message: error.message, status: error.status});
    }

    const processedNotificationIds = [];
    for (const notification of notifications) {
      const type = String(notification.type ?? '').toUpperCase();
      const taskId = taskIdFromNotification(notification);
      if (notification.id) processedNotificationIds.push(String(notification.id));
      if (type === 'APPLICATION_ACCEPTED' && taskId) {
        const application = applications.get(taskId) ?? {title: notification.title, budget: 0};
        application.status = 'ACCEPTED';
        applications.set(taskId, application);
        state.tasksAccepted += 1;
      }
      if (type === 'SUBMISSION_APPROVED') {
        state.lastApprovalNotification = sanitize({taskId, title: notification.title, message: notification.message, createdAt: notification.createdAt});
      }
      if (type === 'SUBMISSION_REJECTED') {
        state.lastRejectionNotification = sanitize({taskId, title: notification.title, message: notification.message, createdAt: notification.createdAt});
      }
    }

    for (const [taskId, application] of applications.entries()) {
      if (application.status !== 'ACCEPTED' || submitted.has(taskId)) continue;
      const task = taskMap.get(taskId) ?? {id: taskId, title: application.title};
      let messages = [];
      try {
        const payload = await requestJson('GET', `/api/agent/tasks/${encodeURIComponent(taskId)}/messages?limit=100`, {apiKey: credentials.apiKey});
        messages = Array.isArray(payload?.messages) ? payload.messages : Array.isArray(payload) ? payload : [];
      } catch {}
      const deliverable = await buildDeliverable(task, messages);
      if (!deliverable) continue;
      try {
        const result = await requestJson('POST', `/api/agent/tasks/${encodeURIComponent(taskId)}/submit`, {
          apiKey: credentials.apiKey,
          body: {
            feedback: deliverable.slice(0, 18_000),
            deliverable: {
              format: 'markdown',
              content: deliverable.slice(0, 80_000),
              aiAuthorshipDisclosed: true,
              externalActionsClaimed: false,
            },
            timeSpent: 1,
          },
          timeout: 90_000,
        });
        submitted.add(taskId);
        application.status = 'SUBMITTED';
        state.submissionsMade += 1;
        state.writesPerformed.push(`submission:${taskId}`);
        state.lastSubmissionReceipt = sanitize({taskId, submissionId: firstString(result, new Set(['submissionid', 'submission_id', 'id'])), status: result?.status ?? result?.submission?.status});
        await persist('Record TaskForce submission', true);
      } catch (error) {
        state.lastSubmissionError = sanitize({taskId, message: error.message, status: error.status, payload: error.payload});
      }
    }

    if (processedNotificationIds.length) {
      try {
        await requestJson('POST', '/api/agent/notifications/read', {
          apiKey: credentials.apiKey,
          body: {notificationIds: processedNotificationIds},
        });
      } catch {}
    }

    if (loop % 5 === 0 || state.submissionsMade > 0) await refreshIncome(credentials.apiKey);
    state.applications = [...applications.entries()].map(([taskId, value]) => ({taskId, ...value}));
    state.status = state.verifiedIncomeUsdc > 0 ? 'income_verified' : 'waiting_for_paid_work';
    await persist('Refresh TaskForce paid-work worker');

    if (state.verifiedIncomeUsdc > 0) break;
    await sleep(30_000);
  }

  await refreshIncome(credentials.apiKey);
  state.finishedAt = now();
  state.status = state.verifiedIncomeUsdc > 0 ? 'income_verified' : 'run_window_completed';
  await persist('Finish TaskForce paid-work worker', true);
} catch (error) {
  state.status = 'failed';
  state.failedAt = now();
  state.error = sanitize({message: error.message, status: error.status, payload: error.payload});
  await persist('Record TaskForce worker failure', true);
  process.exitCode = 1;
}
