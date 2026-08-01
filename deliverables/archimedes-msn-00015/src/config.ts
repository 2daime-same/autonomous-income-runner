import { tokenProviderFromEnvironment } from './auth.js';
import type { GitHubClientOptions } from './types.js';
import { environmentBoolean, environmentInteger } from './validation.js';
import { VERSION } from './version.js';

const DEFAULT_BASE_URL = 'https://api.github.com';
const DEFAULT_API_VERSION = '2026-03-10';
const DEFAULT_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_RESPONSE_BYTES = 5_000_000;
const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_MAX_RETRY_DELAY_MS = 5_000;
const DEFAULT_MAX_PAGES = 5;
const DEFAULT_MAX_FILES = 500;
const DEFAULT_USER_AGENT = `archimedes-github-pr-mcp/${VERSION}`;

export function optionsFromEnvironment(
  environment: NodeJS.ProcessEnv = process.env,
  fetchImpl: typeof fetch = fetch,
  now: () => Date = () => new Date(),
): GitHubClientOptions {
  const baseUrl = environment.GITHUB_API_BASE_URL ?? DEFAULT_BASE_URL;
  const apiVersion = environment.GITHUB_API_VERSION ?? DEFAULT_API_VERSION;
  const timeoutMs = environmentInteger(
    environment.GITHUB_TIMEOUT_MS,
    DEFAULT_TIMEOUT_MS,
    1_000,
    120_000,
    'GITHUB_TIMEOUT_MS',
  );
  const maxResponseBytes = environmentInteger(
    environment.GITHUB_MAX_RESPONSE_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
    16_384,
    25_000_000,
    'GITHUB_MAX_RESPONSE_BYTES',
  );
  const maxRetries = environmentInteger(
    environment.GITHUB_MAX_RETRIES,
    DEFAULT_MAX_RETRIES,
    0,
    5,
    'GITHUB_MAX_RETRIES',
  );
  const maxRetryDelayMs = environmentInteger(
    environment.GITHUB_MAX_RETRY_DELAY_MS,
    DEFAULT_MAX_RETRY_DELAY_MS,
    0,
    30_000,
    'GITHUB_MAX_RETRY_DELAY_MS',
  );
  const maxPages = environmentInteger(
    environment.GITHUB_MAX_PAGES,
    DEFAULT_MAX_PAGES,
    1,
    20,
    'GITHUB_MAX_PAGES',
  );
  const maxFiles = environmentInteger(
    environment.GITHUB_MAX_FILES,
    DEFAULT_MAX_FILES,
    1,
    3_000,
    'GITHUB_MAX_FILES',
  );
  const allowWrites = environmentBoolean(environment.GITHUB_ALLOW_WRITES, false);
  const userAgent = environment.GITHUB_USER_AGENT ?? DEFAULT_USER_AGENT;
  const tokenProvider = tokenProviderFromEnvironment(environment, {
    baseUrl,
    apiVersion,
    timeoutMs,
    allowWrites,
    fetchImpl,
    now,
  });

  return {
    baseUrl,
    apiVersion,
    timeoutMs,
    maxResponseBytes,
    maxRetries,
    maxRetryDelayMs,
    maxPages,
    maxFiles,
    userAgent,
    allowWrites,
    fetchImpl,
    now,
    tokenProvider,
  };
}
