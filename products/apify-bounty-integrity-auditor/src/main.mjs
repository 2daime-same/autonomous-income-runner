import { Actor, log } from 'apify';
import { evaluateIssue, normalizeInput, parseGitHubIssueUrl } from './core.mjs';

const USER_AGENT = 'github-bounty-integrity-auditor/0.1 (+https://github.com/2daime-same/autonomous-income-runner)';
const RETRYABLE = new Set([429, 500, 502, 503, 504]);

function headers(token) {
  return {
    accept: 'application/vnd.github+json',
    'x-github-api-version': '2022-11-28',
    'user-agent': USER_AGENT,
    ...(token ? { authorization: `Bearer ${token}` } : {}),
  };
}

async function fetchJson(url, token, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await fetch(url, { headers: headers(token), signal: AbortSignal.timeout(20_000) });
    if (response.ok) return response.json();
    const text = (await response.text()).slice(0, 500);
    lastError = new Error(`GitHub API ${response.status} for ${url}: ${text}`);
    if (!RETRYABLE.has(response.status) || attempt === attempts) throw lastError;
    const retryAfterSeconds = Number(response.headers.get('retry-after')) || attempt;
    await new Promise((resolve) => setTimeout(resolve, Math.min(10_000, retryAfterSeconds * 1_000)));
  }
  throw lastError;
}

async function fetchComments(owner, repo, number, token, maxComments) {
  if (maxComments <= 0) return [];
  const comments = [];
  let page = 1;
  while (comments.length < maxComments) {
    const perPage = Math.min(100, maxComments - comments.length);
    const pageItems = await fetchJson(
      `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues/${number}/comments?per_page=${perPage}&page=${page}`,
      token,
    );
    if (!Array.isArray(pageItems) || pageItems.length === 0) break;
    comments.push(...pageItems);
    if (pageItems.length < perPage) break;
    page += 1;
  }
  return comments.slice(0, maxComments);
}

async function auditOne(url, options) {
  const parsed = parseGitHubIssueUrl(url);
  const issue = await fetchJson(
    `https://api.github.com/repos/${encodeURIComponent(parsed.owner)}/${encodeURIComponent(parsed.repo)}/issues/${parsed.number}`,
    options.githubToken,
  );
  const comments = options.includeComments
    ? await fetchComments(parsed.owner, parsed.repo, parsed.number, options.githubToken, options.maxComments)
    : [];
  return evaluateIssue({ issue, comments });
}

await Actor.init();
try {
  const input = normalizeInput((await Actor.getInput()) ?? {});
  log.info(`Auditing ${input.issueUrls.length} public GitHub paid-issue candidate(s).`);

  for (const url of input.issueUrls) {
    try {
      const result = await auditOne(url, input);
      await Actor.pushData(result);
      log.info(`${result.verdict}: ${url}`, { score: result.score, rewardAmountUsd: result.rewardAmountUsd });
    } catch (error) {
      const failure = {
        canonicalUrl: url,
        checkedAt: new Date().toISOString(),
        verdict: 'fetch_failed',
        score: 0,
        confidence: 'low',
        error: error instanceof Error ? error.message : String(error),
        dataHandling: 'No input secret is included in this result.',
      };
      await Actor.pushData(failure);
      log.warning(`Audit failed for ${url}: ${failure.error}`);
    }
  }
} finally {
  await Actor.exit();
}
