import { GitHubApiError } from './errors.js';
import { asJsonValue } from './json.js';
import type {
  AuthIntent,
  GitHubClientOptions,
  GitHubTokenProvider,
  HttpResult,
  JsonValue,
} from './types.js';
import {
  normalizeApiBaseUrl,
  rateLimitFromHeaders,
  retryDelayMilliseconds,
} from './validation.js';

const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);
const SAFE_API_PATH = /^repos\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/(?:pulls|issues)(?:\/[A-Za-z0-9_.\/-]+)?$/;

function defaultSleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    timer.unref?.();
  });
}

function requestId(headers: Headers): string | null {
  return headers.get('x-github-request-id');
}

async function readBoundedText(response: Response, maximumBytes: number): Promise<string> {
  if (!response.body) {
    return '';
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      if (value) {
        total += value.byteLength;
        if (total > maximumBytes) {
          await reader.cancel().catch(() => undefined);
          throw new GitHubApiError(
            'response_too_large',
            `GitHub response exceeded ${maximumBytes} bytes.`,
            {
              status: response.status,
              requestId: requestId(response.headers),
              rateLimit: rateLimitFromHeaders(response.headers),
            },
          );
        }
        chunks.push(value);
      }
    }
  } finally {
    reader.releaseLock();
  }
  const output = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(output);
}

function safeUpstreamMessage(text: string): string | null {
  try {
    const value = JSON.parse(text) as unknown;
    if (
      typeof value === 'object' &&
      value !== null &&
      typeof (value as { message?: unknown }).message === 'string'
    ) {
      const message = (value as { message: string }).message.replace(/\s+/g, ' ').trim();
      return message.slice(0, 300) || null;
    }
  } catch {
    return null;
  }
  return null;
}

function publicErrorForResponse(response: Response, bodyText: string): GitHubApiError {
  const status = response.status;
  const rateLimit = rateLimitFromHeaders(response.headers);
  const id = requestId(response.headers);
  const upstreamMessage = safeUpstreamMessage(bodyText);
  const suffix = upstreamMessage ? ` ${upstreamMessage}` : '';

  if (status === 401) {
    return new GitHubApiError(
      'authentication_failed',
      `GitHub authentication failed.${suffix}`,
      { status, requestId: id, rateLimit },
    );
  }
  if (
    status === 403 &&
    (rateLimit.remaining === 0 ||
      response.headers.has('retry-after') ||
      /(?:secondary|rate) limit/i.test(upstreamMessage ?? ''))
  ) {
    return new GitHubApiError('rate_limited', `GitHub rate limit was exhausted.${suffix}`, {
      status,
      retryable: true,
      requestId: id,
      rateLimit,
    });
  }
  if (status === 403) {
    return new GitHubApiError('forbidden', `GitHub denied this operation.${suffix}`, {
      status,
      requestId: id,
      rateLimit,
    });
  }
  if (status === 404) {
    return new GitHubApiError('not_found', `The requested GitHub resource was not found.${suffix}`, {
      status,
      requestId: id,
      rateLimit,
    });
  }
  if (status === 409) {
    return new GitHubApiError('conflict', `GitHub reported a conflict.${suffix}`, {
      status,
      requestId: id,
      rateLimit,
    });
  }
  if (status === 422) {
    return new GitHubApiError('validation_failed', `GitHub rejected the request.${suffix}`, {
      status,
      requestId: id,
      rateLimit,
    });
  }
  if (status === 429) {
    return new GitHubApiError('rate_limited', `GitHub returned HTTP 429.${suffix}`, {
      status,
      retryable: true,
      requestId: id,
      rateLimit,
    });
  }
  return new GitHubApiError('upstream_error', `GitHub returned HTTP ${status}.${suffix}`, {
    status,
    retryable: RETRYABLE_STATUS.has(status),
    requestId: id,
    rateLimit,
  });
}

export class GitHubHttpClient {
  private readonly baseUrl: URL;
  private readonly apiVersion: string;
  private readonly timeoutMs: number;
  private readonly maxResponseBytes: number;
  private readonly maxRetries: number;
  private readonly maxRetryDelayMs: number;
  private readonly userAgent: string;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (milliseconds: number) => Promise<void>;
  private readonly now: () => Date;
  readonly tokenProvider: GitHubTokenProvider;

  constructor(options: GitHubClientOptions = {}) {
    this.baseUrl = normalizeApiBaseUrl(options.baseUrl ?? 'https://api.github.com');
    this.apiVersion = options.apiVersion ?? '2026-03-10';
    this.timeoutMs = options.timeoutMs ?? 15_000;
    this.maxResponseBytes = options.maxResponseBytes ?? 5_000_000;
    this.maxRetries = options.maxRetries ?? 2;
    this.maxRetryDelayMs = options.maxRetryDelayMs ?? 5_000;
    this.userAgent = options.userAgent ?? 'archimedes-github-pr-mcp/1.0.0';
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.sleep = options.sleep ?? defaultSleep;
    this.now = options.now ?? (() => new Date());
    this.tokenProvider = options.tokenProvider ?? {
      mode: 'none',
      async token(intent: AuthIntent) {
        if (intent === 'write') {
          throw new GitHubApiError(
            'write_authentication_required',
            'A write-capable GitHub credential is required.',
          );
        }
        return null;
      },
      describe(intent: AuthIntent) {
        return intent === 'read' ? 'public-anonymous' : 'unavailable';
      },
    };

    if (!/^\d{4}-\d{2}-\d{2}$/.test(this.apiVersion)) {
      throw new GitHubApiError(
        'invalid_configuration',
        'GITHUB_API_VERSION must use YYYY-MM-DD format.',
      );
    }
    if (!Number.isSafeInteger(this.timeoutMs) || this.timeoutMs < 1_000 || this.timeoutMs > 120_000) {
      throw new GitHubApiError('invalid_configuration', 'timeoutMs must be between 1000 and 120000.');
    }
    if (
      !Number.isSafeInteger(this.maxResponseBytes) ||
      this.maxResponseBytes < 16_384 ||
      this.maxResponseBytes > 25_000_000
    ) {
      throw new GitHubApiError(
        'invalid_configuration',
        'maxResponseBytes must be between 16384 and 25000000.',
      );
    }
    if (!Number.isSafeInteger(this.maxRetries) || this.maxRetries < 0 || this.maxRetries > 5) {
      throw new GitHubApiError('invalid_configuration', 'maxRetries must be between 0 and 5.');
    }
    if (
      !Number.isSafeInteger(this.maxRetryDelayMs) ||
      this.maxRetryDelayMs < 0 ||
      this.maxRetryDelayMs > 30_000
    ) {
      throw new GitHubApiError(
        'invalid_configuration',
        'maxRetryDelayMs must be between 0 and 30000.',
      );
    }
    if (!this.userAgent.trim() || this.userAgent.length > 200 || /[\r\n]/.test(this.userAgent)) {
      throw new GitHubApiError(
        'invalid_configuration',
        'userAgent must be a non-empty single line containing at most 200 characters.',
      );
    }
  }

  async getJson(
    path: string,
    query: Readonly<Record<string, string | number | boolean | undefined>> = {},
    accept = 'application/vnd.github+json',
  ): Promise<HttpResult<JsonValue>> {
    const result = await this.request('GET', path, { query, accept, intent: 'read' });
    try {
      return { ...result, data: asJsonValue(JSON.parse(result.data) as unknown) };
    } catch (error) {
      throw new GitHubApiError('invalid_response', 'GitHub response was not valid JSON.', {
        status: result.status,
        requestId: result.requestId,
        rateLimit: result.rateLimit,
        cause: error,
      });
    }
  }

  async getText(
    path: string,
    query: Readonly<Record<string, string | number | boolean | undefined>> = {},
    accept = 'application/vnd.github.v3.diff',
  ): Promise<HttpResult<string>> {
    return this.request('GET', path, { query, accept, intent: 'read' });
  }

  async postJson(
    path: string,
    body: JsonValue,
    accept = 'application/vnd.github+json',
  ): Promise<HttpResult<JsonValue>> {
    const result = await this.request('POST', path, { body, accept, intent: 'write' });
    if (!result.data.trim()) {
      return { ...result, data: null };
    }
    try {
      return { ...result, data: asJsonValue(JSON.parse(result.data) as unknown) };
    } catch (error) {
      throw new GitHubApiError('invalid_response', 'GitHub response was not valid JSON.', {
        status: result.status,
        requestId: result.requestId,
        rateLimit: result.rateLimit,
        cause: error,
      });
    }
  }

  private async request(
    method: 'GET' | 'POST',
    path: string,
    options: {
      query?: Readonly<Record<string, string | number | boolean | undefined>>;
      body?: JsonValue;
      accept: string;
      intent: AuthIntent;
    },
  ): Promise<HttpResult<string>> {
    this.assertSafePath(path);
    if (!options.accept.trim() || options.accept.length > 200 || /[\r\n]/.test(options.accept)) {
      throw new GitHubApiError('invalid_request', 'Accept header must be a non-empty single line.');
    }
    const initialUrl = new URL(path.replace(/^\/+/, ''), this.baseUrl);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined) {
        initialUrl.searchParams.set(key, String(value));
      }
    }

    const maximumAttempts = method === 'GET' ? this.maxRetries + 1 : 1;
    let lastError: unknown;
    for (let attempt = 0; attempt < maximumAttempts; attempt += 1) {
      try {
        return await this.requestOnce(method, initialUrl, options, attempt);
      } catch (error) {
        lastError = error;
        const retryable = error instanceof GitHubApiError && error.retryable;
        if (method !== 'GET' || !retryable || attempt + 1 >= maximumAttempts) {
          throw error;
        }
        if (error instanceof GitHubApiError && error.status === null) {
          const delay = Math.min(this.maxRetryDelayMs, 250 * 2 ** attempt);
          if (delay > 0) {
            await this.sleep(delay);
          }
        }
      }
    }
    throw lastError;
  }

  private async requestOnce(
    method: 'GET' | 'POST',
    initialUrl: URL,
    options: {
      body?: JsonValue;
      accept: string;
      intent: AuthIntent;
    },
    attempt: number,
  ): Promise<HttpResult<string>> {
    let url = new URL(initialUrl);
    const token = await this.tokenProvider.token(options.intent);
    for (let redirectCount = 0; redirectCount <= 3; redirectCount += 1) {
      const headers: Record<string, string> = {
        Accept: options.accept,
        'User-Agent': this.userAgent,
        'X-GitHub-Api-Version': this.apiVersion,
      };
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
      if (method === 'POST') {
        headers['Content-Type'] = 'application/json';
      }

      let response: Response;
      try {
        response = await this.fetchImpl(url, {
          method,
          redirect: 'manual',
          signal: AbortSignal.timeout(this.timeoutMs),
          headers,
          ...(method === 'POST' ? { body: JSON.stringify(options.body ?? null) } : {}),
        });
      } catch (error) {
        throw new GitHubApiError(
          'network_error',
          'GitHub request failed before a response was received.',
          { retryable: method === 'GET', cause: error },
        );
      }

      if ([301, 302, 303, 307, 308].includes(response.status)) {
        const location = response.headers.get('location');
        if (method !== 'GET' || !location || redirectCount === 3) {
          throw new GitHubApiError('redirect_refused', 'GitHub redirect was refused.', {
            status: response.status,
            requestId: requestId(response.headers),
            rateLimit: rateLimitFromHeaders(response.headers),
          });
        }
        const redirected = new URL(location, url);
        if (redirected.origin !== this.baseUrl.origin) {
          throw new GitHubApiError(
            'redirect_refused',
            'GitHub redirect left the configured API origin.',
            {
              status: response.status,
              requestId: requestId(response.headers),
              rateLimit: rateLimitFromHeaders(response.headers),
            },
          );
        }
        url = redirected;
        continue;
      }

      const text = await readBoundedText(response, this.maxResponseBytes);
      if (!response.ok) {
        const error = publicErrorForResponse(response, text);
        if (
          method === 'GET' &&
          error.retryable &&
          attempt < this.maxRetries &&
          this.maxRetryDelayMs > 0
        ) {
          const delay = retryDelayMilliseconds(
            response.headers,
            this.now(),
            250 * 2 ** attempt,
            this.maxRetryDelayMs,
          );
          if (delay > 0) {
            await this.sleep(delay);
          }
        }
        throw error;
      }

      return {
        data: text,
        status: response.status,
        requestId: requestId(response.headers),
        rateLimit: rateLimitFromHeaders(response.headers),
        url: url.toString(),
      };
    }
    throw new GitHubApiError('redirect_refused', 'Too many GitHub redirects.');
  }

  private assertSafePath(path: string): void {
    const normalized = path.replace(/^\/+/, '');
    if (
      !SAFE_API_PATH.test(normalized) ||
      normalized.includes('..') ||
      normalized.includes('\\') ||
      normalized.includes('?') ||
      normalized.includes('#')
    ) {
      throw new GitHubApiError(
        'invalid_path',
        'GitHub API path is outside the supported pull-request and issue endpoints.',
      );
    }
  }
}
