import { ArchimedesApiError } from './errors.js';

const SAFE_ID = /^[A-Za-z0-9_-]{8,128}$/;

function isLoopback(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

export function normalizeBaseUrl(input: string): URL {
  let url: URL;
  try {
    url = new URL(input);
  } catch (error) {
    throw new ArchimedesApiError('invalid_base_url', 'ARCHIMEDES_BASE_URL is not a valid URL.', {
      cause: error,
    });
  }
  if (url.username || url.password) {
    throw new ArchimedesApiError('invalid_base_url', 'ARCHIMEDES_BASE_URL must not contain user information.');
  }
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopback(url.hostname))) {
    throw new ArchimedesApiError(
      'invalid_base_url',
      'ARCHIMEDES_BASE_URL must use HTTPS, except for loopback test servers.',
    );
  }
  if (url.search || url.hash) {
    throw new ArchimedesApiError(
      'invalid_base_url',
      'ARCHIMEDES_BASE_URL must not contain a query string or fragment.',
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
): number {
  const selected = value ?? fallback;
  if (!Number.isSafeInteger(selected) || selected < minimum || selected > maximum) {
    throw new ArchimedesApiError(
      'invalid_argument',
      `Expected an integer between ${minimum} and ${maximum}; received ${String(selected)}.`,
    );
  }
  return selected;
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
    throw new ArchimedesApiError(
      'invalid_argument',
      `${name} must contain at most ${maximum} characters.`,
    );
  }
  return normalized;
}

export function publicIdentifier(value: string, kind: string): string {
  const normalized = value.trim();
  if (!SAFE_ID.test(normalized)) {
    throw new ArchimedesApiError(
      'invalid_identifier',
      `${kind} must be 8-128 characters containing only letters, digits, underscore, or hyphen.`,
    );
  }
  return normalized;
}

export function retryAfterMilliseconds(value: string | null, now: Date): number | null {
  if (!value) {
    return null;
  }
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(Math.round(seconds * 1_000), 5_000);
  }
  const date = Date.parse(value);
  return Number.isNaN(date) ? null : Math.min(Math.max(0, date - now.getTime()), 5_000);
}
