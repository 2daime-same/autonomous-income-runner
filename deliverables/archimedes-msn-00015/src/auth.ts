import { createSign } from 'node:crypto';

import { GitHubApiError } from './errors.js';
import type { AuthIntent, GitHubAppOptions, GitHubTokenProvider, JsonObject } from './types.js';
import { normalizeApiBaseUrl, normalizePrivateKey } from './validation.js';

const APP_TOKEN_SAFETY_MARGIN_MS = 60_000;

function base64Url(value: string | Buffer): string {
  return Buffer.from(value)
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

export function createGitHubAppJwt(
  appId: string,
  privateKey: string,
  now: Date = new Date(),
): string {
  const numericAppId = appId.trim();
  if (!/^\d+$/.test(numericAppId)) {
    throw new GitHubApiError('invalid_configuration', 'GITHUB_APP_ID must be numeric.');
  }
  const issuedAt = Math.floor(now.getTime() / 1_000) - 60;
  const expiresAt = Math.floor(now.getTime() / 1_000) + 540;
  const header = base64Url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const payload = base64Url(JSON.stringify({ iat: issuedAt, exp: expiresAt, iss: numericAppId }));
  const signingInput = `${header}.${payload}`;
  try {
    const signer = createSign('RSA-SHA256');
    signer.update(signingInput);
    signer.end();
    return `${signingInput}.${base64Url(signer.sign(privateKey))}`;
  } catch (error) {
    throw new GitHubApiError('invalid_configuration', 'GitHub App private key could not sign a JWT.', {
      cause: error,
    });
  }
}

export class NoTokenProvider implements GitHubTokenProvider {
  readonly mode = 'none' as const;

  async token(intent: AuthIntent): Promise<string | null> {
    if (intent === 'write') {
      throw new GitHubApiError(
        'write_authentication_required',
        'A write-capable GitHub token or GitHub App installation is required.',
      );
    }
    return null;
  }

  describe(intent: AuthIntent): string {
    return intent === 'write' ? 'unavailable' : 'public-anonymous';
  }
}

export class PatTokenProvider implements GitHubTokenProvider {
  readonly mode = 'pat' as const;

  constructor(
    private readonly readToken: string | null,
    private readonly writeToken: string | null,
    private readonly allowWrites: boolean,
  ) {}

  async token(intent: AuthIntent): Promise<string | null> {
    if (intent === 'read') {
      return this.readToken ?? this.writeToken;
    }
    if (!this.allowWrites) {
      throw new GitHubApiError(
        'writes_disabled',
        'Write tools are disabled. Set GITHUB_ALLOW_WRITES=true after reviewing the permission boundary.',
      );
    }
    if (!this.writeToken) {
      throw new GitHubApiError(
        'write_authentication_required',
        'GITHUB_WRITE_TOKEN or GITHUB_TOKEN is required for write tools.',
      );
    }
    return this.writeToken;
  }

  describe(intent: AuthIntent): string {
    if (intent === 'read') {
      return this.readToken || this.writeToken ? 'personal-access-token' : 'public-anonymous';
    }
    return this.allowWrites && this.writeToken ? 'personal-access-token' : 'unavailable';
  }
}

interface CachedInstallationToken {
  token: string;
  expiresAtMs: number;
}

export class GitHubAppTokenProvider implements GitHubTokenProvider {
  readonly mode = 'app' as const;
  private readonly baseUrl: URL;
  private readonly privateKey: string;
  private readonly cache = new Map<AuthIntent, CachedInstallationToken>();

  constructor(
    private readonly options: GitHubAppOptions,
    private readonly allowWrites: boolean,
  ) {
    this.baseUrl = normalizeApiBaseUrl(options.baseUrl);
    this.privateKey = normalizePrivateKey(options.privateKey);
    if (!/^\d+$/.test(options.installationId.trim())) {
      throw new GitHubApiError(
        'invalid_configuration',
        'GITHUB_APP_INSTALLATION_ID must be numeric.',
      );
    }
  }

  async token(intent: AuthIntent): Promise<string> {
    if (intent === 'write' && !this.allowWrites) {
      throw new GitHubApiError(
        'writes_disabled',
        'Write tools are disabled. Set GITHUB_ALLOW_WRITES=true after reviewing the permission boundary.',
      );
    }
    const nowMs = this.options.now().getTime();
    const cached = this.cache.get(intent);
    if (cached && cached.expiresAtMs - APP_TOKEN_SAFETY_MARGIN_MS > nowMs) {
      return cached.token;
    }
    const generated = await this.generateInstallationToken(intent);
    this.cache.set(intent, generated);
    return generated.token;
  }

  describe(intent: AuthIntent): string {
    return intent === 'write' && !this.allowWrites
      ? 'unavailable'
      : `github-app-installation-${intent}`;
  }

  private async generateInstallationToken(intent: AuthIntent): Promise<CachedInstallationToken> {
    const jwt = createGitHubAppJwt(this.options.appId, this.privateKey, this.options.now());
    const url = new URL(
      `app/installations/${this.options.installationId}/access_tokens`,
      this.baseUrl,
    );
    const permissions: JsonObject =
      intent === 'write'
        ? { contents: 'read', issues: 'write', pull_requests: 'write' }
        : { contents: 'read', issues: 'read', pull_requests: 'read' };

    let response: Response;
    try {
      response = await this.options.fetchImpl(url, {
        method: 'POST',
        redirect: 'error',
        signal: AbortSignal.timeout(this.options.timeoutMs),
        headers: {
          Accept: 'application/vnd.github+json',
          Authorization: `Bearer ${jwt}`,
          'Content-Type': 'application/json',
          'User-Agent': 'archimedes-github-pr-mcp/1.0.0',
          'X-GitHub-Api-Version': this.options.apiVersion,
        },
        body: JSON.stringify({ permissions }),
      });
    } catch (error) {
      throw new GitHubApiError(
        'github_app_authentication_failed',
        'GitHub App installation token request failed.',
        { retryable: false, cause: error },
      );
    }

    const text = await response.text();
    if (!response.ok) {
      throw new GitHubApiError(
        'github_app_authentication_failed',
        `GitHub App installation token request returned HTTP ${response.status}.`,
        { status: response.status },
      );
    }

    let payload: unknown;
    try {
      payload = JSON.parse(text) as unknown;
    } catch (error) {
      throw new GitHubApiError(
        'github_app_authentication_failed',
        'GitHub App token response was not valid JSON.',
        { cause: error },
      );
    }
    if (
      typeof payload !== 'object' ||
      payload === null ||
      typeof (payload as { token?: unknown }).token !== 'string' ||
      typeof (payload as { expires_at?: unknown }).expires_at !== 'string'
    ) {
      throw new GitHubApiError(
        'github_app_authentication_failed',
        'GitHub App token response did not include token and expires_at.',
      );
    }
    const token = (payload as { token: string }).token;
    const expiresAtMs = Date.parse((payload as { expires_at: string }).expires_at);
    if (!token || Number.isNaN(expiresAtMs)) {
      throw new GitHubApiError(
        'github_app_authentication_failed',
        'GitHub App token response contained invalid values.',
      );
    }
    return { token, expiresAtMs };
  }
}

export function tokenProviderFromEnvironment(
  environment: NodeJS.ProcessEnv,
  options: {
    baseUrl: string;
    apiVersion: string;
    timeoutMs: number;
    allowWrites: boolean;
    fetchImpl: typeof fetch;
    now: () => Date;
  },
): GitHubTokenProvider {
  const mode = (environment.GITHUB_AUTH_MODE ?? 'auto').trim().toLowerCase();
  if (!['auto', 'none', 'pat', 'app'].includes(mode)) {
    throw new GitHubApiError(
      'invalid_configuration',
      'GITHUB_AUTH_MODE must be auto, none, pat, or app.',
    );
  }

  const genericToken = environment.GITHUB_TOKEN?.trim() || null;
  const readToken = environment.GITHUB_READ_TOKEN?.trim() || genericToken;
  const writeToken = environment.GITHUB_WRITE_TOKEN?.trim() || genericToken;
  const hasPat = Boolean(readToken || writeToken);
  const appId = environment.GITHUB_APP_ID?.trim() || '';
  const installationId = environment.GITHUB_APP_INSTALLATION_ID?.trim() || '';
  const privateKey =
    environment.GITHUB_APP_PRIVATE_KEY?.trim() ||
    environment.GITHUB_APP_PRIVATE_KEY_BASE64?.trim() ||
    '';
  const hasApp = Boolean(appId && installationId && privateKey);

  if (mode === 'none') {
    return new NoTokenProvider();
  }
  if (mode === 'pat' || (mode === 'auto' && hasPat)) {
    if (!hasPat) {
      throw new GitHubApiError(
        'invalid_configuration',
        'PAT mode requires GITHUB_TOKEN, GITHUB_READ_TOKEN, or GITHUB_WRITE_TOKEN.',
      );
    }
    return new PatTokenProvider(readToken, writeToken, options.allowWrites);
  }
  if (mode === 'app' || (mode === 'auto' && hasApp)) {
    if (!hasApp) {
      throw new GitHubApiError(
        'invalid_configuration',
        'App mode requires GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, and a private key.',
      );
    }
    return new GitHubAppTokenProvider(
      {
        baseUrl: options.baseUrl,
        apiVersion: options.apiVersion,
        appId,
        installationId,
        privateKey,
        timeoutMs: options.timeoutMs,
        fetchImpl: options.fetchImpl,
        now: options.now,
      },
      options.allowWrites,
    );
  }
  return new NoTokenProvider();
}
