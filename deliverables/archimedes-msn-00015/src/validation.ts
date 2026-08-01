import { GitHubApiError } from './errors.js';
import type { DiffSide, RateLimitInfo, ReviewEvent } from './types.js';

const OWNER_REPOSITORY = /^[A-Za-z0-9_.-]{1,100}$/;
const LABEL = /^[^\u0000-\u001f\u007f]{1,100}$/;

function isLoopback(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

export function normalizeApiBaseUrl(input: string): URL {
  let url: URL;
  try {
    url = new URL(input);
  } catch (error) {
    throw new GitHubApiError('invalid_base_url', 'GITHUB_API_BASE_URL is not a valid URL.', {
      cause: error,
    });
  }
  if (url.username || url.password) {
    throw new GitHubApiError('invalid_base_url', 'GITHUB_API_BASE_URL must not contain user information.');
  }
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopback(url.hostname))) {
    throw new GitHubApiError(
      'invalid_base_url',
      'GITHUB_API_BASE_URL must use HTTPS, except for loopback test servers.',
    );
  }
  if (url.search || url.hash) {
    throw new GitHubApiError(
      'invalid_base_url',
      'GITHUB_API_BASE_URL must not contain a query string or fragment.',
    );
  }
  url.pathname = url.pathname.replace(/\/+$/, '') + '/';
  return url;
}

export function boundedInteger(
  value: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
  name = 'value',
): number {
  const selected = value ?? fallback;
  if (!Number.isSafeInteger(selected) || selected < minimum || selected > maximum) {
    throw new GitHubApiError(
      'invalid_argument',
      `${name} must be an integer between ${minimum} and ${maximum}.`,
    );
  }
  return selected;
}

export function environmentInteger(
  value: string | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
  name: string,
): number {
  if (value === undefined || value.trim() === '') {
    return fallback;
  }
  const parsed = Number(value);
  return boundedInteger(parsed, fallback, minimum, maximum, name);
}

export function environmentBoolean(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value.trim() === '') {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) {
    return true;
  }
  if (['0', 'false', 'no', 'off'].includes(normalized)) {
    return false;
  }
  throw new GitHubApiError('invalid_configuration', 'Expected a boolean environment value.');
}

export function ownerOrRepository(value: string, name: string): string {
  const normalized = value.trim();
  if (!OWNER_REPOSITORY.test(normalized) || normalized === '.' || normalized === '..') {
    throw new GitHubApiError(
      'invalid_identifier',
      `${name} must contain only letters, digits, dot, underscore, or hyphen.`,
    );
  }
  return normalized;
}

export function pullNumber(value: number): number {
  return boundedInteger(value, value, 1, 2_147_483_647, 'pull_number');
}

export function positiveIdentifier(value: number, name: string): number {
  return boundedInteger(value, value, 1, Number.MAX_SAFE_INTEGER, name);
}

export function requiredText(value: string, name: string, maximum: number): string {
  const normalized = value.trim();
  if (!normalized) {
    throw new GitHubApiError('invalid_argument', `${name} must not be empty.`);
  }
  if (normalized.length > maximum) {
    throw new GitHubApiError('invalid_argument', `${name} must contain at most ${maximum} characters.`);
  }
  return normalized;
}

export function optionalText(
  value: string | undefined,
  name: string,
  maximum: number,
): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  const normalized = value.trim();
  if (!normalized) {
    return undefined;
  }
  if (normalized.length > maximum) {
    throw new GitHubApiError('invalid_argument', `${name} must contain at most ${maximum} characters.`);
  }
  return normalized;
}

export function repositoryPath(value: string): string {
  const normalized = value.trim().replace(/^\/+/, '');
  if (
    !normalized ||
    normalized.length > 1_024 ||
    normalized.includes('\u0000') ||
    normalized.includes('\\') ||
    normalized.split('/').some((segment) => !segment || segment === '.' || segment === '..')
  ) {
    throw new GitHubApiError('invalid_path', 'path must be a normalized repository-relative path.');
  }
  return normalized;
}

export function labels(value: readonly string[]): string[] {
  if (value.length < 1 || value.length > 20) {
    throw new GitHubApiError('invalid_argument', 'labels must contain between 1 and 20 values.');
  }
  const normalized = [...new Set(value.map((item) => item.trim()))];
  if (normalized.some((item) => !LABEL.test(item))) {
    throw new GitHubApiError('invalid_argument', 'Each label must contain 1-100 printable characters.');
  }
  return normalized;
}

export function reviewEvent(value: string): ReviewEvent {
  if (value === 'APPROVE' || value === 'COMMENT' || value === 'REQUEST_CHANGES') {
    return value;
  }
  throw new GitHubApiError('invalid_argument', 'event must be APPROVE, COMMENT, or REQUEST_CHANGES.');
}

export function diffSide(value: string): DiffSide {
  if (value === 'LEFT' || value === 'RIGHT') {
    return value;
  }
  throw new GitHubApiError('invalid_argument', 'side must be LEFT or RIGHT.');
}

export function assertConfirmation(confirm: boolean): void {
  if (confirm !== true) {
    throw new GitHubApiError(
      'confirmation_required',
      'This write tool requires confirm=true in the same tool call.',
    );
  }
}

function headerInteger(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export function rateLimitFromHeaders(headers: Headers): RateLimitInfo {
  const resetSeconds = headerInteger(headers.get('x-ratelimit-reset'));
  return {
    limit: headerInteger(headers.get('x-ratelimit-limit')),
    remaining: headerInteger(headers.get('x-ratelimit-remaining')),
    used: headerInteger(headers.get('x-ratelimit-used')),
    resetAt:
      resetSeconds === null ? null : new Date(resetSeconds * 1_000).toISOString(),
    resource: headers.get('x-ratelimit-resource'),
  };
}

export function retryDelayMilliseconds(
  headers: Headers,
  now: Date,
  fallbackMs: number,
  maximumMs: number,
): number {
  const retryAfter = headers.get('retry-after');
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) {
      return Math.min(maximumMs, Math.round(seconds * 1_000));
    }
    const date = Date.parse(retryAfter);
    if (!Number.isNaN(date)) {
      return Math.min(maximumMs, Math.max(0, date - now.getTime()));
    }
  }

  const remaining = headerInteger(headers.get('x-ratelimit-remaining'));
  const reset = headerInteger(headers.get('x-ratelimit-reset'));
  if (remaining === 0 && reset !== null) {
    return Math.min(maximumMs, Math.max(0, reset * 1_000 - now.getTime()));
  }
  return Math.min(maximumMs, fallbackMs);
}

export function normalizePrivateKey(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new GitHubApiError('invalid_configuration', 'GitHub App private key must not be empty.');
  }
  if (trimmed.includes('BEGIN') && trimmed.includes('PRIVATE KEY')) {
    return trimmed.replace(/\\n/g, '\n');
  }
  try {
    const decoded = Buffer.from(trimmed, 'base64').toString('utf8').trim();
    if (decoded.includes('BEGIN') && decoded.includes('PRIVATE KEY')) {
      return decoded;
    }
  } catch {
    // Fall through to a stable configuration error below.
  }
  throw new GitHubApiError(
    'invalid_configuration',
    'GitHub App private key must be PEM text or base64-encoded PEM text.',
  );
}
