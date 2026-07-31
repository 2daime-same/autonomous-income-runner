export class ArchimedesApiError extends Error {
  readonly code: string;
  readonly status: number | null;
  readonly retryable: boolean;
  readonly rateLimitRemaining: string | null;

  constructor(
    code: string,
    message: string,
    options: {
      status?: number | null;
      retryable?: boolean;
      rateLimitRemaining?: string | null;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = 'ArchimedesApiError';
    this.code = code;
    this.status = options.status ?? null;
    this.retryable = options.retryable ?? false;
    this.rateLimitRemaining = options.rateLimitRemaining ?? null;
  }
}
