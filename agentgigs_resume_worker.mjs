import {createHash} from 'node:crypto';
import {chmod, mkdir, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import process from 'node:process';

const ORIGIN = process.env.AGENTGIGS_ORIGIN ?? 'https://www.agentgigs.io';
const PUBLIC_STATE = 'agentgigs-output/public-state.json';
const PRIVATE_STATE = 'agentgigs-output/private-state.cms';
const APPLIED_LEDGER = 'agentgigs-output/applied-job-hashes.json';
const CERTIFICATE = 'keys/superteam-state-public.crt';
const RESUME_STATE_PATH = process.env.AGENTGIGS_RESUME_STATE_PATH ?? '/tmp/agentgigs-resume.json';
const MAX_APPLICATIONS = Math.min(1, Math.max(0, Number(process.env.AGENTGIGS_MAX_APPLICATIONS ?? '1')));
const EXPECTED_PROFILE = process.env.AGENTGIGS_EXPECTED_PROFILE ?? 'BoundaryLedger Agent 097062';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const now = () => new Date().toISOString();
const SECRET_KEY = /api.?key|authorization|bearer|secret|token|private|credential|password|cookie|email|refresh/i;

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      output[key] = SECRET_KEY.test(key) ? '[REDACTED]' : sanitize(item);
    }
    return output;
  }
  if (typeof value === 'string') {
    return value
      .replace(/\bage_[A-Za-z0-9._~+/=-]{8,}\b/g, '[REDACTED_API_KEY]')
      .replace(/\beyJ[A-Za-z0-9._-]{20,}\b/g, '[REDACTED_JWT]')
      .replace(/[A-Za-z0-9._%+-]+@gmail\.com/gi, '[REDACTED_EMAIL]');
  }
  return value;
}

function opaque(value) {
  return createHash('sha256').update(String(value)).digest('hex').slice(0, 20);
}

async function atomicJson(file, value, mode = 0o600) {
  await mkdir(path.dirname(file), {recursive: true});
  const temporary = `${file}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {mode});
  await rename(temporary, file);
  await chmod(file, mode);
}

function run(command, args) {
  return spawnSync(command, args, {
    cwd: process.cwd(),
    encoding: 'utf8',
    stdio: 'ignore',
    env: process.env,
  });
}

async function api(method, endpoint, {bearer, apiKey, body, timeout = 45_000, retries = 0} = {}) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const headers = {Accept: 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (bearer) headers.Authorization = `Bearer ${bearer}`;
    if (apiKey) headers['X-API-Key'] = apiKey;

    try {
      const response = await fetch(`${ORIGIN}${endpoint}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        redirect: 'follow',
        signal: AbortSignal.timeout(timeout),
      });
      const text = await response.text();
      let payload;
      try {
        payload = text ? JSON.parse(text) : null;
      } catch {
        payload = {text: text.slice(0, 2000)};
      }
      if (response.ok) return payload;

      const error = new Error(`${method} ${endpoint} failed (HTTP ${response.status})`);
      error.status = response.status;
      error.payload = sanitize(payload);
      if (method !== 'GET' || response.status < 500 || attempt >= retries) throw error;
      lastError = error;
    } catch (error) {
      lastError = error;
      if (method !== 'GET' || attempt >= retries) throw error;
    }
    await sleep(1000 * (2 ** attempt));
  }
  throw lastError;
}

function firstString(value, keys) {
  if (Array.isArray(value)) {
    for (const item of value) {
      const result = firstString(item, keys);
      if (result) return result;
    }
    return null;
  }
  if (!value || typeof value !== 'object') return null;
  for (const [key, item] of Object.entries(value)) {
    const normalized = key.replace(/[-_]/g, '').toLowerCase();
    if (keys.has(normalized) && typeof item === 'string' && item.trim()) return item.trim();
    const result = firstString(item, keys);
    if (result) return result;
  }
  return null;
}

async function encryptPrivate(value) {
  const plain = `/tmp/agentgigs-private-${process.pid}.json`;
  await writeFile(plain, `${JSON.stringify(value, null, 2)}\n`, {mode: 0o600});
  await chmod(plain, 0o600);
  await mkdir(path.dirname(PRIVATE_STATE), {recursive: true});
  const result = run('openssl', [
    'cms', '-encrypt', '-binary', '-aes256', '-outform', 'DER',
    '-in', plain, '-out', PRIVATE_STATE, CERTIFICATE,
  ]);
  await rm(plain, {force: true});
  if (result.status !== 0) throw new Error('AgentGigs credential encryption failed');
  await chmod(PRIVATE_STATE, 0o600);
}

async function loadApplied() {
  try {
    const payload = JSON.parse(await readFile(APPLIED_LEDGER, 'utf8'));
    const hashes = Array.isArray(payload?.jobHashes)
      ? payload.jobHashes
      : Array.isArray(payload?.hashes)
        ? payload.hashes
        : [];
    return new Set(hashes.map(String));
  } catch {
    return new Set();
  }
}

async function saveApplied(set) {
  await atomicJson(APPLIED_LEDGER, {updatedAt: now(), jobHashes: [...set].sort()}, 0o644);
}

function listFrom(payload, keys) {
  if (Array.isArray(payload)) return payload;
  for (const key of keys) {
    if (Array.isArray(payload?.[key])) return payload[key];
  }
  return [];
}

function normalizedCode(error) {
  return String(
    error?.payload?.code
      ?? error?.payload?.error?.code
      ?? error?.payload?.error
      ?? '',
  ).toUpperCase();
}

function normalizedMessage(error) {
  return String(
    error?.payload?.message
      ?? error?.payload?.error?.message
      ?? error?.message
      ?? '',
  ).slice(0, 500);
}

function isStripeRequired(error) {
  return error?.status === 403 && (
    normalizedCode(error).includes('STRIPE')
      || /stripe account required|connect.*stripe|payment settings/i.test(normalizedMessage(error))
  );
}

function isDuplicate(error) {
  return error?.status === 409
    || /already applied|duplicate|conflict/i.test(`${normalizedCode(error)} ${normalizedMessage(error)}`);
}

const blocked = [
  /adult|porn|sexual|escort|dating manipulation/i,
  /weapon|explosive|malware|ransomware|phishing|credential theft/i,
  /hack into|bypass authentication|steal|dox|private data/i,
  /fake review|fake engagement|mass dm|spam|astroturf/i,
  /kyc bypass|captcha solving|account farming|impersonat/i,
  /private key|seed phrase|wallet signing|send funds|deposit required/i,
  /physical delivery|in-person|onsite|phone call|take photos?/i,
  /medical diagnosis|legal representation|guaranteed investment return/i,
];
const preferred = /research|analysis|data|writing|content|documentation|readme|api|openapi|python|javascript|typescript|coding|testing|qa|json|csv|automation/i;
const oversized = /full mobile app|full-stack marketplace|entire platform|complete rewrite|train (?:an?|the) model|fine[- ]?tune|30 days|14 days|24\/7 outreach/i;

function jobText(job) {
  return [job?.title, job?.description, job?.category, JSON.stringify(job?.tags ?? [])]
    .filter(Boolean)
    .join('\n')
    .slice(0, 40_000);
}

function jobSuitable(job) {
  const text = jobText(job);
  if (!job?.id || !text.trim()) return false;
  if (blocked.some(pattern => pattern.test(text))) return false;
  if (oversized.test(text)) return false;
  if (!preferred.test(text)) return false;
  const min = Number(job.budget_min ?? 0);
  const max = Number(job.budget_max ?? 0);
  if (!Number.isFinite(max) || max <= 0) return false;
  if (Number.isFinite(min) && min > 100_000) return false;
  return true;
}

function proposalPrice(job) {
  const min = Math.max(100, Number(job?.budget_min ?? 0));
  const max = Math.max(min, Number(job?.budget_max ?? min));
  return Math.round(Math.min(max, Math.max(min, max * 0.8)));
}

function proposal(job) {
  const category = String(job?.category ?? 'digital-services').replace(/[^A-Za-z0-9 _-]/g, '').slice(0, 40) || 'digital-services';
  return [
    'I am a transparently disclosed AI-operated worker.',
    `For this ${category} request, I will produce a concise, source-bounded deliverable that directly addresses the stated acceptance criteria.`,
    'My process is: restate the scope, collect only relevant evidence, complete the work in a reproducible format, run a consistency and factuality check, and include one revision.',
    'I will not invent access, prior client history, test results, or human credentials.',
  ].join(' ').slice(0, 900);
}

function earningsCents(payload) {
  const candidates = [
    payload?.earnings?.totalEarnings,
    payload?.totalEarnings,
    payload?.earnings?.total_earnings,
    payload?.total_earnings,
    payload?.balance,
  ];
  for (const candidate of candidates) {
    const value = Number(candidate);
    if (!Number.isFinite(value)) continue;
    if (Number.isInteger(value)) return Math.max(0, value);
    return Math.max(0, Math.round(value * 100));
  }
  return 0;
}

function applicationSummary(applications) {
  const counts = {};
  const acceptedHashes = [];
  for (const application of applications) {
    const status = String(application?.status ?? 'unknown').toLowerCase();
    counts[status] = Number(counts[status] ?? 0) + 1;
    if (/accepted|selected|funded|in_progress|in-progress|hired/.test(status)) {
      const id = application?.id ?? application?.job_id ?? application?.job?.id;
      if (id) acceptedHashes.push(opaque(id));
    }
  }
  return {counts, acceptedHashes: [...new Set(acceptedHashes)].slice(0, 25)};
}

let resume;
try {
  resume = JSON.parse(await readFile(RESUME_STATE_PATH, 'utf8'));
  await chmod(RESUME_STATE_PATH, 0o600);
} catch {
  throw new Error('Encrypted AgentGigs state was not decrypted into the resume path');
}

const email = String(resume?.email ?? '').trim();
const password = String(resume?.password ?? '');
const profileName = String(resume?.profileName ?? '').trim();
if (!email || !password || !profileName) throw new Error('Resume state is missing required AgentGigs account fields');
if (EXPECTED_PROFILE && profileName !== EXPECTED_PROFILE) {
  throw new Error(`Refusing to resume unexpected AgentGigs profile: ${profileName}`);
}

let bearer = typeof resume?.bearer === 'string' ? resume.bearer : null;
let refreshToken = typeof resume?.refreshToken === 'string' ? resume.refreshToken : null;
let apiKey = typeof resume?.apiKey === 'string' ? resume.apiKey : null;
let userId = typeof resume?.userId === 'string' ? resume.userId : null;
const applied = await loadApplied();
let privateStateReady = false;

const state = {
  updatedAt: now(),
  status: 'resuming_existing_account',
  accountReused: true,
  registrationAttempted: false,
  profileName,
  accountHash: opaque(email),
  expectedProfileMatched: true,
  emailVerified: true,
  profileExisting: true,
  apiKeyReused: false,
  apiKeyRegenerated: false,
  stripeRequired: false,
  applicationsSubmittedThisRun: 0,
  applicationsObserved: 0,
  applicationStatusCounts: {},
  acceptedApplications: 0,
  acceptedApplicationHashes: [],
  deliverablesSubmitted: 0,
  verifiedEarningsCents: 0,
  availableJobCount: 0,
  suitableJobCount: 0,
  notificationsObserved: 0,
  relevantNotificationsObserved: 0,
  duplicateApplicationsObserved: 0,
  writesPerformed: [],
  credentialsRecordedInPlaintext: false,
  privateJobContentRecorded: false,
};

async function savePrivateState() {
  await encryptPrivate({
    email,
    password,
    userId,
    bearer,
    refreshToken,
    apiKey,
    profileName,
    runId: String(process.env.GITHUB_RUN_ID ?? resume?.runId ?? ''),
    resumedAt: now(),
  });
  privateStateReady = true;
}

async function fetchSnapshot() {
  const [applicationsResult, earningsResult, notificationsResult] = await Promise.allSettled([
    api('GET', '/api/agent/applications?limit=100', {apiKey, retries: 1}),
    api('GET', '/api/agent/earnings', {apiKey, retries: 1}),
    api('GET', '/api/agent/notifications?limit=100', {apiKey, retries: 1}),
  ]);

  if (applicationsResult.status === 'fulfilled') {
    const applications = listFrom(applicationsResult.value, ['applications', 'items', 'results']);
    const summary = applicationSummary(applications);
    state.applicationsObserved = applications.length;
    state.applicationStatusCounts = summary.counts;
    state.acceptedApplicationHashes = summary.acceptedHashes;
    state.acceptedApplications = summary.acceptedHashes.length;
  } else {
    state.lastApplicationsError = sanitize({
      status: applicationsResult.reason?.status,
      code: normalizedCode(applicationsResult.reason),
    });
  }

  if (earningsResult.status === 'fulfilled') {
    state.earningsSnapshot = sanitize({
      tier: earningsResult.value?.tier,
      totalEarnings: earningsResult.value?.earnings?.totalEarnings ?? earningsResult.value?.totalEarnings,
      completedJobs: earningsResult.value?.earnings?.completedJobs ?? earningsResult.value?.completedJobs,
      pendingEarnings: earningsResult.value?.earnings?.pendingEarnings ?? earningsResult.value?.pendingEarnings,
    });
    state.verifiedEarningsCents = earningsCents(earningsResult.value);
  } else {
    state.lastEarningsError = sanitize({
      status: earningsResult.reason?.status,
      code: normalizedCode(earningsResult.reason),
    });
  }

  if (notificationsResult.status === 'fulfilled') {
    const notifications = listFrom(notificationsResult.value, ['notifications', 'items', 'results']);
    state.notificationsObserved = notifications.length;
    state.relevantNotificationsObserved = notifications.filter(notification =>
      /application|accepted|selected|hired|payment|payout|message|reply|job/i.test(
        [notification?.type, notification?.title, notification?.category].filter(Boolean).join(' '),
      )
    ).length;
  } else {
    state.lastNotificationsError = sanitize({
      status: notificationsResult.reason?.status,
      code: normalizedCode(notificationsResult.reason),
    });
  }
}

try {
  if (apiKey) {
    try {
      await api('GET', '/api/agent/jobs/available?limit=1', {apiKey, retries: 1});
      state.apiKeyReused = true;
    } catch (error) {
      if ([401, 403].includes(error?.status)) apiKey = null;
      else throw error;
    }
  }

  if (!apiKey) {
    const login = await api('POST', '/api/auth/login', {body: {email, password}});
    bearer = firstString(login, new Set(['accesstoken', 'token']));
    refreshToken = firstString(login, new Set(['refreshtoken'])) ?? refreshToken;
    userId = firstString(login, new Set(['userid', 'id'])) ?? userId;
    if (!bearer) throw new Error('Existing AgentGigs account login returned no access token');

    const keyPayload = await api('POST', '/api/agent/api-key', {bearer, body: {}});
    apiKey = firstString(keyPayload, new Set(['apikey', 'key']));
    if (!apiKey) throw new Error('AgentGigs API-key generation returned no key');
    state.apiKeyRegenerated = true;
    state.writesPerformed.push('api_key_generation_for_existing_account');
  }

  await savePrivateState();

  try {
    const profile = await api('GET', '/api/agent/profile', {apiKey, retries: 1});
    const observedName = String(profile?.agent?.name ?? profile?.name ?? '').trim();
    if (observedName && observedName !== profileName) {
      throw new Error(`AgentGigs profile mismatch: expected ${profileName}, observed ${observedName}`);
    }
    state.profileVerifiedByApi = Boolean(observedName);
  } catch (error) {
    state.profileVerifiedByApi = false;
    state.profileLookupError = sanitize({status: error?.status, code: normalizedCode(error)});
  }

  await fetchSnapshot();

  const inventory = await api('GET', '/api/agent/jobs/available?limit=100', {apiKey, retries: 1});
  const jobs = listFrom(inventory, ['jobs', 'items', 'results']);
  const suitable = jobs
    .filter(jobSuitable)
    .sort((a, b) => Number(b?.match_score ?? 0) - Number(a?.match_score ?? 0));

  state.availableJobCount = jobs.length;
  state.suitableJobCount = suitable.length;
  state.latestInventory = jobs.slice(0, 50).map(job => ({
    jobHash: opaque(job.id),
    category: sanitize(job.category),
    budgetMin: Number(job.budget_min ?? 0),
    budgetMax: Number(job.budget_max ?? 0),
    matchScore: Number(job.match_score ?? 0),
  }));

  for (const job of suitable) {
    if (state.applicationsSubmittedThisRun >= MAX_APPLICATIONS) break;
    const hash = opaque(job.id);
    if (applied.has(hash)) continue;

    try {
      await api('POST', `/api/jobs/${encodeURIComponent(job.id)}/nda`, {apiKey, body: {}});
      state.writesPerformed.push(`nda:${hash}`);
    } catch (error) {
      if (![400, 409].includes(error?.status)) {
        state.lastNdaError = sanitize({jobHash: hash, status: error?.status, code: normalizedCode(error)});
        continue;
      }
    }

    try {
      await api('POST', `/api/jobs/${encodeURIComponent(job.id)}/apply`, {
        apiKey,
        body: {
          message: proposal(job),
          proposed_price: proposalPrice(job),
          estimated_delivery: '24 hours',
        },
      });
      applied.add(hash);
      state.applicationsSubmittedThisRun += 1;
      state.writesPerformed.push(`application:${hash}`);
      state.lastApplication = {
        jobHash: hash,
        category: sanitize(job.category),
        proposedPrice: proposalPrice(job),
      };
    } catch (error) {
      if (isStripeRequired(error)) {
        state.stripeRequired = true;
        state.status = 'blocked_by_stripe_connect';
        state.applicationBlocked = {
          jobHash: hash,
          reason: 'stripe_connect_required',
          status: error?.status,
          budgetMin: Number(job.budget_min ?? 0),
          budgetMax: Number(job.budget_max ?? 0),
          matchScore: Number(job.match_score ?? 0),
        };
        break;
      }
      if (isDuplicate(error)) {
        applied.add(hash);
        state.duplicateApplicationsObserved += 1;
        continue;
      }
      state.lastApplicationError = sanitize({
        jobHash: hash,
        status: error?.status,
        code: normalizedCode(error),
      });
    }
  }

  await fetchSnapshot();
  if (state.verifiedEarningsCents > 0) state.status = 'verified_revenue_observed';
  else if (state.acceptedApplications > 0) state.status = 'accepted_work_requires_delivery';
  else if (state.applicationsSubmittedThisRun > 0) state.status = 'application_submitted_waiting';
  else if (!state.stripeRequired) state.status = 'verified_searching_and_waiting';

  await savePrivateState();
} catch (error) {
  state.status = 'resume_error';
  state.lastError = sanitize({
    message: error?.message,
    status: error?.status,
    code: normalizedCode(error),
  });
  process.exitCode = 1;
} finally {
  state.updatedAt = now();
  state.privateStateReady = privateStateReady;
  await atomicJson(PUBLIC_STATE, sanitize(state), 0o644);
  await saveApplied(applied);
  await rm(RESUME_STATE_PATH, {force: true});
}
