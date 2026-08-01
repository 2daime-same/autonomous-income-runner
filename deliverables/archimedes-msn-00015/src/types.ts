export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export type AuthIntent = 'read' | 'write';
export type ReviewEvent = 'APPROVE' | 'COMMENT' | 'REQUEST_CHANGES';
export type DiffSide = 'LEFT' | 'RIGHT';

export interface RateLimitInfo {
  limit: number | null;
  remaining: number | null;
  used: number | null;
  resetAt: string | null;
  resource: string | null;
}

export interface HttpResult<T> {
  data: T;
  status: number;
  requestId: string | null;
  rateLimit: RateLimitInfo;
  url: string;
}

export interface GitHubTokenProvider {
  readonly mode: 'none' | 'pat' | 'app';
  token(intent: AuthIntent): Promise<string | null>;
  describe(intent: AuthIntent): string;
}

export interface GitHubClientOptions {
  baseUrl?: string;
  apiVersion?: string;
  timeoutMs?: number;
  maxResponseBytes?: number;
  maxRetries?: number;
  maxRetryDelayMs?: number;
  maxPages?: number;
  maxFiles?: number;
  userAgent?: string;
  allowWrites?: boolean;
  fetchImpl?: typeof fetch;
  sleep?: (milliseconds: number) => Promise<void>;
  now?: () => Date;
  tokenProvider?: GitHubTokenProvider;
}

export interface ListPullRequestsInput {
  owner: string;
  repo: string;
  state?: 'open' | 'closed' | 'all' | undefined;
  sort?: 'created' | 'updated' | 'popularity' | 'long-running' | undefined;
  direction?: 'asc' | 'desc' | undefined;
  max_items?: number | undefined;
}

export interface PullRequestLocator {
  owner: string;
  repo: string;
  pull_number: number;
}

export interface GetPullRequestDiffInput extends PullRequestLocator {
  max_files?: number | undefined;
  max_lines_per_file?: number | undefined;
  include_patch?: boolean | undefined;
}

export interface ListPullRequestCommentsInput extends PullRequestLocator {
  include_issue_comments?: boolean | undefined;
  include_reviews?: boolean | undefined;
  include_inline_comments?: boolean | undefined;
  max_items?: number | undefined;
}

export interface PostReviewCommentInput extends PullRequestLocator {
  body: string;
  path: string;
  line: number;
  side: DiffSide;
  start_line?: number | undefined;
  start_side?: DiffSide | undefined;
  confirm: boolean;
}

export interface SubmitReviewInput extends PullRequestLocator {
  event: ReviewEvent;
  body?: string | undefined;
  review_id?: number | undefined;
  confirm: boolean;
}

export interface AddLabelsInput extends PullRequestLocator {
  labels: string[];
  confirm: boolean;
}

export interface RequestChangesInput extends PullRequestLocator {
  body: string;
  confirm: boolean;
}

export interface ParsedDiffLine {
  position: number;
  kind: 'context' | 'addition' | 'deletion';
  text: string;
  oldLine: number | null;
  newLine: number | null;
}

export interface ParsedDiffHunk {
  header: string;
  oldStart: number;
  oldCount: number;
  newStart: number;
  newCount: number;
  lines: ParsedDiffLine[];
}

export interface ParsedFileDiff {
  path: string;
  previousPath: string | null;
  status: string;
  additions: number;
  deletions: number;
  changes: number;
  binary: boolean | null;
  patchUnavailable: boolean;
  patchTruncated: boolean;
  hunks: ParsedDiffHunk[];
  rawPatch: string | null;
}

export interface GitHubAppOptions {
  baseUrl: string;
  apiVersion: string;
  appId: string;
  installationId: string;
  privateKey: string;
  timeoutMs: number;
  fetchImpl: typeof fetch;
  now: () => Date;
}
