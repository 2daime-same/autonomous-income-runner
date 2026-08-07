const GITHUB_ISSUE_RE = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/(?:issues|pull)\/(\d+)(?:[/?#].*)?$/i;
const GITHUB_PULL_RE = /https:\/\/github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)\/pull\/(\d+)/gi;
const MARKDOWN_PULL_RE = /\[[^\]]*#(\d+)[^\]]*\]\(https?:\/\/(?:oss\.)?issuehunt\.io\/r\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)\/pull\/(\d+)\)/gi;

const PROMPT_EXTRACTION_PATTERNS = [
  /system\s+prompt/i,
  /hidden\s+(?:prompt|instructions?)/i,
  /initial\s+(?:directives?|instructions?)/i,
  /runtime\s+instructions?/i,
  /pre[- ]user[- ]message/i,
  /session\s+metadata/i,
];

const SECRET_REQUEST_PATTERNS = [
  /(?:post|paste|share|reveal|upload).{0,50}(?:private\s+key|seed\s+phrase|api\s+key|access\s+token|password|cookie)/i,
  /(?:wallet|payout|bank).{0,40}(?:details?|credentials?).{0,40}(?:comment|issue|public)/i,
];

const SOCIAL_SPAM_PATTERNS = [
  /(?:like|retweet|repost|upvote).{0,40}(?:to\s+qualify|for\s+payment|before\s+claiming)/i,
  /(?:mass|bulk).{0,20}(?:comment|review|message|post)/i,
];

const HOLD_OFF_PATTERNS = [
  /\bdo\s+not\s+(?:work|start|submit|open\s+a\s+pr)\b/i,
  /\bdon['’]?t\s+(?:work|start|submit|open\s+a\s+pr)\b/i,
  /\bnot\s+(?:accepting|ready\s+for|looking\s+for)\s+(?:prs?|contributions?|implementations?)\b/i,
  /\bhold\s+off\b/i,
  /\bplease\s+wait\b/i,
  /\balready\s+(?:claimed|assigned|being\s+worked\s+on)\b/i,
];

const REWARD_LABEL_RE = /(?:bounty|reward|funded|paid|prize)/i;

export function parseGitHubIssueUrl(value) {
  if (typeof value !== 'string') return null;
  const match = value.trim().match(GITHUB_ISSUE_RE);
  if (!match) return null;
  return {
    owner: match[1],
    repo: match[2],
    number: Number(match[3]),
    canonicalUrl: `https://github.com/${match[1]}/${match[2]}/issues/${Number(match[3])}`,
  };
}

function numberFromText(raw) {
  if (!raw) return null;
  const cleaned = raw.replace(/,/g, '');
  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function pushReward(target, reward) {
  if (!reward || !Number.isFinite(reward.amountUsd) || reward.amountUsd <= 0) return;
  const key = `${reward.provider}:${reward.amountUsd}:${reward.status}`;
  if (target.some((entry) => `${entry.provider}:${entry.amountUsd}:${entry.status}` === key)) return;
  target.push(reward);
}

export function extractRewardEvidence(issue) {
  const body = String(issue?.body ?? '');
  const rewardText = body.replace(/%24/gi, '$').replace(/%2C/gi, ',');
  const labels = (issue?.labels ?? []).map((label) => typeof label === 'string' ? label : label?.name).filter(Boolean);
  const rewards = [];

  for (const match of rewardText.matchAll(/IssueHunt[-_\s]*\$?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(Funded|Rewarded)/gi)) {
    pushReward(rewards, {
      provider: 'IssueHunt',
      amountUsd: numberFromText(match[1]),
      status: match[2].toLowerCase(),
      evidence: match[0].slice(0, 160),
    });
  }

  for (const match of rewardText.matchAll(/Backers\s*\(Total:\s*\$([0-9][0-9,]*(?:\.[0-9]+)?)\)/gi)) {
    pushReward(rewards, {
      provider: body.includes('issuehunt') ? 'IssueHunt' : 'body',
      amountUsd: numberFromText(match[1]),
      status: /has\s+been\s+rewarded/i.test(body) ? 'rewarded' : 'funded',
      evidence: match[0].slice(0, 160),
    });
  }

  for (const match of rewardText.matchAll(/(?:reward|bounty|prize)(?:\s+(?:of|is|:))?\s*\$([0-9][0-9,]*(?:\.[0-9]+)?)/gi)) {
    pushReward(rewards, {
      provider: /algora\.io/i.test(body) ? 'Algora' : /opire\.dev/i.test(body) ? 'Opire' : 'body',
      amountUsd: numberFromText(match[1]),
      status: /rewarded|paid|completed/i.test(body) ? 'rewarded' : 'advertised',
      evidence: match[0].slice(0, 160),
    });
  }

  const rewardLabel = labels.find((label) => REWARD_LABEL_RE.test(label));
  if (rewardLabel && rewards.length === 0) {
    const amountMatch = `${issue?.title ?? ''} ${rewardText.slice(0, 600)}`.match(/\$([0-9][0-9,]*(?:\.[0-9]+)?)/);
    const amount = numberFromText(amountMatch?.[1]);
    if (amount) {
      pushReward(rewards, {
        provider: /algora/i.test(body) ? 'Algora' : /opire/i.test(body) ? 'Opire' : 'label-and-body',
        amountUsd: amount,
        status: 'advertised',
        evidence: `label:${rewardLabel}`,
      });
    }
  }

  return rewards.sort((a, b) => b.amountUsd - a.amountUsd);
}

export function extractPullRequestLinks(texts) {
  const links = new Set();
  for (const value of texts) {
    const text = String(value ?? '');
    for (const match of text.matchAll(GITHUB_PULL_RE)) {
      links.add(`https://github.com/${match[1]}/${match[2]}/pull/${Number(match[3])}`);
    }
    for (const match of text.matchAll(MARKDOWN_PULL_RE)) {
      links.add(`https://github.com/${match[2]}/${match[3]}/pull/${Number(match[4])}`);
    }
  }
  return [...links].sort();
}

export function detectSafetyFlags(texts) {
  const joined = texts.map((value) => String(value ?? '')).join('\n');
  const flags = [];
  if (PROMPT_EXTRACTION_PATTERNS.some((pattern) => pattern.test(joined))) {
    flags.push('requests hidden prompts, internal instructions, or session metadata');
  }
  if (SECRET_REQUEST_PATTERNS.some((pattern) => pattern.test(joined))) {
    flags.push('requests secrets, private keys, credentials, or private payout data');
  }
  if (SOCIAL_SPAM_PATTERNS.some((pattern) => pattern.test(joined))) {
    flags.push('requires social spam or artificial engagement');
  }
  return flags;
}

export function detectMaintainerHoldoffs(comments) {
  const holdoffs = [];
  for (const comment of comments ?? []) {
    const association = String(comment?.author_association ?? comment?.association ?? '').toUpperCase();
    if (!['OWNER', 'MEMBER', 'COLLABORATOR'].includes(association)) continue;
    const body = String(comment?.body ?? '');
    if (!HOLD_OFF_PATTERNS.some((pattern) => pattern.test(body))) continue;
    holdoffs.push({
      login: comment?.user?.login ?? comment?.login ?? null,
      association,
      excerpt: body.replace(/\s+/g, ' ').trim().slice(0, 280),
      url: comment?.html_url ?? comment?.url ?? null,
    });
  }
  return holdoffs;
}

export function evaluateIssue({ issue, comments = [], checkedAt = new Date().toISOString() }) {
  const title = String(issue?.title ?? '');
  const body = String(issue?.body ?? '');
  const commentBodies = comments.map((comment) => String(comment?.body ?? ''));
  const rewardEvidence = extractRewardEvidence(issue);
  const submittedPullRequests = extractPullRequestLinks([body, ...commentBodies]);
  const safetyFlags = detectSafetyFlags([title, body, ...commentBodies]);
  const maintainerHoldoffs = detectMaintainerHoldoffs(comments);
  const isPullRequest = Boolean(issue?.pull_request);
  const state = String(issue?.state ?? 'unknown').toLowerCase();
  const rewarded = rewardEvidence.some((reward) => reward.status === 'rewarded');
  const amountUsd = rewardEvidence.reduce((max, reward) => Math.max(max, reward.amountUsd), 0);
  const updatedAt = issue?.updated_at ?? null;
  const ageDays = updatedAt ? Math.max(0, (Date.parse(checkedAt) - Date.parse(updatedAt)) / 86_400_000) : null;

  const blockers = [];
  if (isPullRequest) blockers.push('input resolves to a pull request rather than an issue');
  if (state !== 'open') blockers.push(`canonical issue state is ${state}`);
  if (rewarded) blockers.push('reward evidence says the bounty was already rewarded');
  if (amountUsd <= 0) blockers.push('no positive dollar reward was verified from the canonical issue');
  if (submittedPullRequests.length > 0) blockers.push(`${submittedPullRequests.length} submitted or referenced pull request(s) detected`);
  if (maintainerHoldoffs.length > 0) blockers.push('maintainer hold-off or prior-claim signal detected');
  blockers.push(...safetyFlags);

  let score = 50;
  if (state === 'open') score += 15;
  if (amountUsd > 0) score += Math.min(20, Math.log10(amountUsd + 1) * 8);
  if (rewardEvidence.some((reward) => ['IssueHunt', 'Algora', 'Opire'].includes(reward.provider))) score += 10;
  if (submittedPullRequests.length > 0) score -= Math.min(30, submittedPullRequests.length * 12);
  if (maintainerHoldoffs.length > 0) score -= 35;
  if (safetyFlags.length > 0) score -= 60;
  if (rewarded) score -= 55;
  if (state !== 'open') score -= 45;
  if (ageDays !== null && ageDays > 365) score -= 8;
  score = Math.max(0, Math.min(100, Math.round(score)));

  let verdict = 'verify_manually';
  if (safetyFlags.length > 0 || rewarded || state !== 'open' || isPullRequest) verdict = 'avoid';
  else if (amountUsd > 0 && submittedPullRequests.length === 0 && maintainerHoldoffs.length === 0) verdict = 'candidate';
  else if (submittedPullRequests.length > 0 || maintainerHoldoffs.length > 0) verdict = 'competitive_or_blocked';

  const confidence = rewardEvidence.some((reward) => ['IssueHunt', 'Algora', 'Opire'].includes(reward.provider))
    ? 'high'
    : amountUsd > 0 ? 'medium' : 'low';

  return {
    canonicalUrl: issue?.html_url ?? issue?.url ?? null,
    repository: issue?.repository_url ? issue.repository_url.split('/repos/')[1] ?? null : null,
    issueNumber: issue?.number ?? null,
    title,
    state,
    updatedAt,
    checkedAt,
    rewardAmountUsd: amountUsd || null,
    rewardEvidence,
    submittedPullRequests,
    competitorCount: submittedPullRequests.length,
    maintainerHoldoffs,
    safetyFlags,
    blockers: [...new Set(blockers)],
    score,
    verdict,
    confidence,
    dataHandling: 'Public GitHub text was treated as untrusted data and was not executed or followed as instructions.',
  };
}

export function normalizeInput(input) {
  const issueUrls = Array.isArray(input?.issueUrls) ? input.issueUrls : [];
  const uniqueUrls = [...new Set(issueUrls.map((url) => String(url).trim()).filter(Boolean))];
  if (uniqueUrls.length === 0) throw new Error('issueUrls must contain at least one public GitHub issue URL.');
  if (uniqueUrls.length > 50) throw new Error('A maximum of 50 issue URLs is allowed per run.');
  for (const url of uniqueUrls) {
    if (!parseGitHubIssueUrl(url)) throw new Error(`Unsupported GitHub issue URL: ${url}`);
  }
  return {
    issueUrls: uniqueUrls,
    includeComments: input?.includeComments !== false,
    maxComments: Math.max(0, Math.min(100, Number.isFinite(input?.maxComments) ? Math.trunc(input.maxComments) : 50)),
    githubToken: typeof input?.githubToken === 'string' && input.githubToken.trim() ? input.githubToken.trim() : null,
  };
}
