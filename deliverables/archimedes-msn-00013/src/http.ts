import { ArchimedesApiError } from './errors.js';
import { asJsonValue } from './json.js';
import type { ArchimedesClientOptions, JsonValue } from './types.js';
import { normalizeBaseUrl, retryAfterMilliseconds } from './validation.js';

const SAFE_PUBLIC_PATH = /^api\/public\/[A-Za-z0-9_/-]+$/;
const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);

function defaultSleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    timer.unref?.();
  });
}

function headerInteger(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function publicErrorForStatus(response: Response): ArchimedesApiError {
  const status = response.status;
  const rateLimitRemaining = response.headers.get('x-ratelimit-remaining');
  if (status === 404) {
    return new ArchimedesApiError('not_found', 'The requested public Archimedes resource was not found.', {
      status,
      rateLimitRemaining,
    });
  }
  if (status === 401 || status === 403) {
    return new ArchimedesApiError(
      'upstream_access_denied',
      `Archimedes public API returned HTTP ${status}.`,
      { status, rateLimitRemaining },
    );
  }
  if (status === 429) {
    return new ArchimedesApiError('rate_limited', 'Archimedes public API returned HTTP 429.', {
      status,
      retryable: true,
      rateLimitRemaining,
    });
  }
  return new ArchimedesApiError('upstream_error', `Archimedes public API returned HTTP ${status}.`, {
    status,
    retryable: RETRYABLE_STATUS.has(status),
    rateLimitRemaining,
  });
}

export class PublicJsonHttpClient {
  private readonly baseUrl: URL;
  private readonly timeoutMs: number;
  private readonly maxResponseBytes: number;
  private readonly maxRetries: number;
  private readonly userAgent: string;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (milliseconds: number) => Promise<void>;
  private readonly now: () => Date;

  constructor(options: ArchimedesClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? 'https://archimedes.market');
    this.timeoutMs = options.timeoutMs ?? 15_000;
    this.maxResponseBytes = options.maxResponseBytes ?? 2_000_000;
    this.maxRetries = options.maxRetries ?? 2;
    this.userAgent = options.userAgent ?? 'archimedes-market-mcp/1.0.0 (+read-only public API client)';
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.sleep = options.sleep ?? defaultSleep;
    this.now = options.now ?? (() => new Date());

    if (!Number.isSafeInteger(this.timeoutMs) || this.timeoutMs < 1_000 || this.timeoutMs > 120_000) {
      throw new ArchimedesApiError('invalid_configuration', 'timeoutMs must be between 1000 and 120000.');
    }
    if (
      !Number.isSafeInteger(this.maxResponseBytes) ||
      this.maxResponseBytes < 1_024 ||
      this.maxResponseBytes > 10_000_000
    ) {
      throw new ArchimedesApiError(
        'invalid_configuration',
        'maxResponseBytes must be between 1024 and 10000000.',
      );
    }
    if (!Number.isSafeInteger(this.maxRetries) || this.maxRetries < 0 || this.maxRetries > 5) {
      throw new ArchimedesApiError('invalid_configuration', 'maxRetries must be between 0 and 5.');
    }
    if (!this.userAgent.trim() || /[\r\n]/.test(this.userAgent)) {
      throw new ArchimedesApiError('invalid_configuration', 'userAgent must be a non-empty single line.');
    }
  }

  async get(
    path: string,
    query: Readonly<Record<string, string | number | boolean | undefined>> = {},
  ): Promise<JsonValue> {
    if (!SAFE_PUBLIC_PATH.test(path) || path.includes('//') || path.includes('..')) {
      throw new ArchimedesApiError('invalid_path', 'Only fixed public Archimedes API paths are allowed.');
    }

    const url = new URL(path, this.baseUrl);
    if (url.origin !== this.baseUrl.origin || !url.pathname.startsWith(this.baseUrl.pathname)) {
      throw new ArchimedesApiError('invalid_path', 'Public API path escaped the configured base URL.');
    }
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }

    let lastError: ArchimedesApiError | null = null;
    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      try {
        const response = await this.fetchOnce(url);
        if (!response.ok) {
          const error = publicErrorForStatus(response);
          await response.body?.cancel().catch(() => undefined);
          if (error.retryable && attempt < this.maxRetries) {
            const retryAfter = retryAfterMilliseconds(response.headers.get('retry-after'), this.now());
            await this.sleep(retryAfter ?? Math.min(250 * 2 ** attempt, 2_000));
            lastError = error;
            continue;
          }
          throw error;
        }
        return await this.readJson(response);
      } catch (error) {
        const normalized = this.normalizeFetchError(error);
        if (normalized.retryable && attempt < this.maxRetries) {
          await this.sleep(Math.min(250 * 2 ** attempt, 2_000));
          lastError = normalized;
          continue;
        }
        throw normalized;
      }
    }

    throw (
      lastError ??
      new ArchimedesApiError('network_error', 'Unable to reach the Archimedes public API.', {
        retryable: true,
      })
    );
  }

  private async fetchOnce(url: URL): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    timeout.unref?.();
    try {
      return await this.fetchImpl(url, {
        method: 'GET',
        headers: {
          accept: 'application/json',
          'user-agent': this.userAgent,
        },
        redirect: 'error',
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
        cache: 'no-store',
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }
  }

  private async readJson(response: Response): Promise<JsonValue> {
    const declaredLength = headerInteger(response.headers.get('content-length'));
    if (declaredLength !== null && declaredLength > this.maxResponseBytes) {
      await response.body?.cancel().catch(() => undefined);
      throw new ArchimedesApiError('response_too_large', 'Public API response exceeded the configured size limit.');
    }

    const bytes = await this.readBoundedBody(response);
    let text: string;
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch (error) {
      throw new ArchimedesApiError('invalid_response', 'Public API response was not valid UTF-8.', {
        cause: error,
      });
    }

    try {
      return asJsonValue(JSON.parse(text) as unknown);
    } catch (error) {
      throw new ArchimedesApiError('invalid_response', 'Public API response was not valid JSON.', {
        cause: error,
      });
    }
  }

  private async readBoundedBody(response: Response): Promise<Uint8Array> {
    if (!response.body) {
      return new Uint8Array();
    }
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    const deadline = Date.now() + this.timeoutMs;
    let total = 0;
    try {
      while (true) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) {
          throw new ArchimedesApiError('timeout', 'Archimedes public API response body timed out.', {
            retryable: true,
          });
        }
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
          const result = await Promise.race([
            reader.read(),
            new Promise<never>((_resolve, reject) => {
              timer = setTimeout(
                () =>
                  reject(
                    new ArchimedesApiError('timeout', 'Archimedes public API response body timed out.', {
                      retryable: true,
                    }),
                  ),
                remaining,
              );
              timer.unref?.();
            }),
          ]);
          if (result.done) {
            break;
          }
          total += result.value.byteLength;
          if (total > this.maxResponseBytes) {
            throw new ArchimedesApiError(
              'response_too_large',
              'Public API response exceeded the configured size limit.',
            );
          }
          chunks.push(result.value);
        } finally {
          if (timer !== undefined) {
            clearTimeout(timer);
          }
        }
      }
    } catch (error) {
      await reader.cancel().catch(() => undefined);
      throw error;
    } finally {
      reader.releaseLock();
    }

    const output = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      output.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return output;
  }

  private normalizeFetchError(error: unknown): ArchimedesApiError {
    if (error instanceof ArchimedesApiError) {
      return error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      return new ArchimedesApiError('timeout', 'Archimedes public API request timed out.', {
        retryable: true,
        cause: error,
      });
    }
    return new ArchimedesApiError('network_error', 'Unable to reach the Archimedes public API.', {
      retryable: true,
      cause: error,
    });
  }
}
