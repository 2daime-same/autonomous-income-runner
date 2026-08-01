import type { RateLimitInfo } from './types.js';

const EMPTY_RATE_LIMIT: RateLimitInfo = {
  limit: null,
  remaining: null,
  used: null,
  resetAt: null,
  resource: null,
};

export class GitHubApiError extends Error {
  readonly code: string;
  readonly status: number | null;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly rateLimit: RateLimitInfo;

  constructor(
    code: string,
    message: string,
    options: {
      status?: number | null;
      retryable?: boolean;
      requestId?: string | null;
      rateLimit?: RateLimitInfo;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = 'GitHubApiError';
    this.code = code;
    this.status = options.status ?? null;
    this.retryable = options.retryable ?? false;
    this.requestId = options.requestId ?? null;
    this.rateLimit = options.rateLimit ?? EMPTY_RATE_LIMIT;
  }
}
