import type { ArchimedesClientOptions } from './types.js';
import { VERSION } from './version.js';

const DEFAULT_BASE_URL = 'https://archimedes.market';
const DEFAULT_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_RESPONSE_BYTES = 2_000_000;
const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_USER_AGENT = `archimedes-market-mcp/${VERSION} (+read-only public API client)`;

function integerFromEnvironment(
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
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}.`);
  }
  return parsed;
}

export function optionsFromEnvironment(
  environment: NodeJS.ProcessEnv = process.env,
): ArchimedesClientOptions {
  return {
    baseUrl: environment.ARCHIMEDES_BASE_URL ?? DEFAULT_BASE_URL,
    timeoutMs: integerFromEnvironment(
      environment.ARCHIMEDES_TIMEOUT_MS,
      DEFAULT_TIMEOUT_MS,
      1_000,
      120_000,
      'ARCHIMEDES_TIMEOUT_MS',
    ),
    maxResponseBytes: integerFromEnvironment(
      environment.ARCHIMEDES_MAX_RESPONSE_BYTES,
      DEFAULT_MAX_RESPONSE_BYTES,
      1_024,
      10_000_000,
      'ARCHIMEDES_MAX_RESPONSE_BYTES',
    ),
    maxRetries: integerFromEnvironment(
      environment.ARCHIMEDES_MAX_RETRIES,
      DEFAULT_MAX_RETRIES,
      0,
      5,
      'ARCHIMEDES_MAX_RETRIES',
    ),
    userAgent: environment.ARCHIMEDES_USER_AGENT ?? DEFAULT_USER_AGENT,
  };
}
