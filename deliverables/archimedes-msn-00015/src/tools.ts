import { GitHubApiError } from './errors.js';
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
    error instanceof GitHubApiError
      ? {
          error: error.code,
          message: error.message,
          status: error.status,
          retryable: error.retryable,
          request_id: error.requestId,
          rate_limit: {
            limit: error.rateLimit.limit,
            remaining: error.rateLimit.remaining,
            used: error.rateLimit.used,
            reset_at: error.rateLimit.resetAt,
            resource: error.rateLimit.resource,
          },
        }
      : {
          error: 'internal_error',
          message: 'The GitHub pull-request tool failed unexpectedly.',
          status: null,
          retryable: false,
          request_id: null,
          rate_limit: {
            limit: null,
            remaining: null,
            used: null,
            reset_at: null,
            resource: null,
          },
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
      throw new GitHubApiError('invalid_response', 'Tool operation did not return a JSON object.');
    }
    return successResult(value);
  } catch (error) {
    return errorResult(error);
  }
}
