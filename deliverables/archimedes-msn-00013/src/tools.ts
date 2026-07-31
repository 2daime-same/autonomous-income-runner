import { ArchimedesApiError } from './errors.js';
import { asJsonValue, isJsonObject } from './json.js';
import type { JsonObject } from './types.js';

function pretty(value: JsonObject): string {
  return JSON.stringify(value, null, 2);
}

export function successResult(value: JsonObject) {
  return {
    content: [{ type: 'text' as const, text: pretty(value) }],
    structuredContent: value,
  };
}

export function errorResult(error: unknown) {
  const value: JsonObject =
    error instanceof ArchimedesApiError
      ? {
          error: error.code,
          message: error.message,
          status: error.status,
          retryable: error.retryable,
          rate_limit_remaining: error.rateLimitRemaining,
        }
      : {
          error: 'internal_error',
          message: 'The read-only Archimedes tool failed unexpectedly.',
          status: null,
          retryable: false,
          rate_limit_remaining: null,
        };

  return {
    content: [{ type: 'text' as const, text: pretty(value) }],
    structuredContent: value,
    isError: true,
  };
}

export async function runTool<T extends object>(operation: () => Promise<T>) {
  try {
    const value = asJsonValue(await operation());
    if (!isJsonObject(value)) {
      throw new ArchimedesApiError('invalid_response', 'Tool operation did not return a JSON object.');
    }
    return successResult(value);
  } catch (error) {
    return errorResult(error);
  }
}
