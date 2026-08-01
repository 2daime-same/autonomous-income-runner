import { parseFileDiff, compactFileDiff, validateDiffLocation } from './diff.js';
import { GitHubApiError } from './errors.js';
import { GitHubHttpClient } from './http.js';
import { asJsonValue, isJsonObject } from './json.js';
import type {
  AddLabelsInput,
  GetPullRequestDiffInput,
  GitHubClientOptions,
  HttpResult,
  JsonObject,
  JsonValue,
  ListPullRequestCommentsInput,
  ListPullRequestsInput,
  PostReviewCommentInput,
  PullRequestLocator,
  RateLimitInfo,
  RequestChangesInput,
  SubmitReviewInput,
} from './types.js';
import {
  assertConfirmation,
  boundedInteger,
  diffSide,
  labels,
  optionalText,
  ownerOrRepository,
  positiveIdentifier,
  pullNumber,
  repositoryPath,
  requiredText,
  reviewEvent,
} from './validation.js';

function object(value: JsonValue, context: string): JsonObject {
  if (!isJsonObject(value)) {
    throw new GitHubApiError('invalid_response', `${context} was not a JSON object.`);
  }
  return value;
}

function array(value: JsonValue, context: string): JsonValue[] {
  if (!Array.isArray(value)) {
    throw new GitHubApiError('invalid_response', `${context} was not a JSON array.`);
  }
  return value;
}

function stringValue(value: JsonValue | undefined): string | null {
  return typeof value === 'string' ? value : null;
}

function numberValue(value: JsonValue | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function booleanValue(value: JsonValue | undefined): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function rateLimitObject(rateLimit: RateLimitInfo): JsonObject {
  return {
    limit: rateLimit.limit,
    remaining: rateLimit.remaining,
    used: rateLimit.used,
    reset_at: rateLimit.resetAt,
    resource: rateLimit.resource,
  };
}

function responseMetadata(result: HttpResult<unknown>): JsonObject {
  return {
    status: result.status,
    request_id: result.requestId,
    rate_limit: rateLimitObject(result.rateLimit),
  };
}

function compactUser(value: JsonValue | undefined): JsonObject | null {
  if (!isJsonObject(value)) {
    return null;
  }
  return {
    login: stringValue(value.login),
    id: numberValue(value.id),
    type: stringValue(value.type),
    html_url: stringValue(value.html_url),
  };
}

function compactPullRequest(value: JsonValue): JsonObject {
  const item = object(value, 'Pull request item');
  const head = isJsonObject(item.head) ? item.head : {};
  const base = isJsonObject(item.base) ? item.base : {};
  const headRepo = isJsonObject(head.repo) ? head.repo : {};
  const baseRepo = isJsonObject(base.repo) ? base.repo : {};
  const labelsValue = Array.isArray(item.labels) ? item.labels : [];
  const labelsCompact = labelsValue
    .filter(isJsonObject)
    .map((label) => ({ name: stringValue(label.name), color: stringValue(label.color) }));
  return {
    number: numberValue(item.number),
    title: stringValue(item.title),
    state: stringValue(item.state),
    draft: booleanValue(item.draft),
    locked: booleanValue(item.locked),
    html_url: stringValue(item.html_url),
    api_url: stringValue(item.url),
    user: compactUser(item.user),
    head: {
      ref: stringValue(head.ref),
      sha: stringValue(head.sha),
      repository: stringValue(headRepo.full_name),
    },
    base: {
      ref: stringValue(base.ref),
      sha: stringValue(base.sha),
      repository: stringValue(baseRepo.full_name),
    },
    labels: asJsonValue(labelsCompact),
    created_at: stringValue(item.created_at),
    updated_at: stringValue(item.updated_at),
    closed_at: stringValue(item.closed_at),
    merged_at: stringValue(item.merged_at),
  };
}

function compactPullRequestDetail(value: JsonValue): JsonObject {
  const item = object(value, 'Pull request detail');
  return {
    ...compactPullRequest(item),
    body: stringValue(item.body),
    mergeable: booleanValue(item.mergeable),
    mergeable_state: stringValue(item.mergeable_state),
    merged: booleanValue(item.merged),
    commits: numberValue(item.commits),
    additions: numberValue(item.additions),
    deletions: numberValue(item.deletions),
    changed_files: numberValue(item.changed_files),
    comments: numberValue(item.comments),
    review_comments: numberValue(item.review_comments),
    requested_reviewers: asJsonValue(
      (Array.isArray(item.requested_reviewers) ? item.requested_reviewers : [])
        .map((user) => compactUser(user))
        .filter((user): user is JsonObject => user !== null),
    ),
  };
}

interface PaginationResult {
  items: JsonValue[];
  lastResponse: HttpResult<JsonValue>;
  pagesFetched: number;
}

export class GitHubPullRequestClient {
  private readonly http: GitHubHttpClient;
  private readonly maxPages: number;
  private readonly maxFiles: number;
  private readonly now: () => Date;

  constructor(options: GitHubClientOptions = {}) {
    this.http = new GitHubHttpClient(options);
    this.maxPages = options.maxPages ?? 5;
    this.maxFiles = options.maxFiles ?? 500;
    this.now = options.now ?? (() => new Date());
    if (!Number.isSafeInteger(this.maxPages) || this.maxPages < 1 || this.maxPages > 20) {
      throw new GitHubApiError('invalid_configuration', 'maxPages must be between 1 and 20.');
    }
    if (!Number.isSafeInteger(this.maxFiles) || this.maxFiles < 1 || this.maxFiles > 3_000) {
      throw new GitHubApiError('invalid_configuration', 'maxFiles must be between 1 and 3000.');
    }
  }

  async listPullRequests(input: ListPullRequestsInput): Promise<JsonObject> {
    const owner = ownerOrRepository(input.owner, 'owner');
    const repo = ownerOrRepository(input.repo, 'repo');
    const state = input.state ?? 'open';
    const sort = input.sort ?? 'updated';
    const direction = input.direction ?? 'desc';
    const maxItems = boundedInteger(input.max_items, 100, 1, 500, 'max_items');
    const result = await this.paginate(
      `repos/${owner}/${repo}/pulls`,
      { state, sort, direction },
      maxItems,
    );
    return {
      source: 'github.com',
      operation: 'list_prs',
      repository: `${owner}/${repo}`,
      auth: this.http.tokenProvider.describe('read'),
      returned: result.items.length,
      pages_fetched: result.pagesFetched,
      truncated: result.items.length === maxItems,
      items: asJsonValue(result.items.map(compactPullRequest)),
      fetched_at: this.now().toISOString(),
      response: responseMetadata(result.lastResponse),
    };
  }

  async getPullRequest(input: PullRequestLocator): Promise<JsonObject> {
    const { owner, repo, number } = this.locator(input);
    const result = await this.http.getJson(`repos/${owner}/${repo}/pulls/${number}`);
    return {
      source: 'github.com',
      operation: 'get_pr',
      repository: `${owner}/${repo}`,
      pull_number: number,
      auth: this.http.tokenProvider.describe('read'),
      item: compactPullRequestDetail(result.data),
      fetched_at: this.now().toISOString(),
      response: responseMetadata(result),
    };
  }

  async getPullRequestDiff(input: GetPullRequestDiffInput): Promise<JsonObject> {
    const { owner, repo, number } = this.locator(input);
    const maximumFiles = Math.min(
      boundedInteger(input.max_files, 100, 1, 500, 'max_files'),
      this.maxFiles,
    );
    const maximumLines = boundedInteger(
      input.max_lines_per_file,
      400,
      1,
      2_000,
      'max_lines_per_file',
    );
    const includePatch = input.include_patch ?? false;
    const result = await this.pullRequestFiles(owner, repo, number, maximumFiles, includePatch);
    const parsed = result.items.map((item) => {
      const file = parseFileDiff(object(item, 'Pull request file'), includePatch);
      return compactFileDiff(file, maximumLines);
    });
    return {
      source: 'github.com',
      operation: 'get_pr_diff',
      repository: `${owner}/${repo}`,
      pull_number: number,
      auth: this.http.tokenProvider.describe('read'),
      returned_files: parsed.length,
      pages_fetched: result.pagesFetched,
      truncated: parsed.length === maximumFiles,
      files: asJsonValue(parsed),
      fetched_at: this.now().toISOString(),
      response: responseMetadata(result.lastResponse),
    };
  }

  async listPullRequestComments(input: ListPullRequestCommentsInput): Promise<JsonObject> {
    const { owner, repo, number } = this.locator(input);
    const maxItems = boundedInteger(input.max_items, 200, 1, 500, 'max_items');
    const includeIssue = input.include_issue_comments ?? true;
    const includeReviews = input.include_reviews ?? true;
    const includeInline = input.include_inline_comments ?? true;
    if (!includeIssue && !includeReviews && !includeInline) {
      throw new GitHubApiError('invalid_argument', 'At least one comment category must be enabled.');
    }

    const groups: Array<Promise<{ kind: string; result: PaginationResult }>> = [];
    if (includeIssue) {
      groups.push(
        this.paginate(`repos/${owner}/${repo}/issues/${number}/comments`, {}, maxItems).then(
          (result) => ({ kind: 'issue_comment', result }),
        ),
      );
    }
    if (includeReviews) {
      groups.push(
        this.paginate(`repos/${owner}/${repo}/pulls/${number}/reviews`, {}, maxItems).then(
          (result) => ({ kind: 'review', result }),
        ),
      );
    }
    if (includeInline) {
      groups.push(
        this.paginate(`repos/${owner}/${repo}/pulls/${number}/comments`, {}, maxItems).then(
          (result) => ({ kind: 'inline_review_comment', result }),
        ),
      );
    }
    const resolved = await Promise.all(groups);
    const combined: JsonObject[] = [];
    let lastResponse: HttpResult<JsonValue> | null = null;
    let pagesFetched = 0;
    for (const group of resolved) {
      lastResponse = group.result.lastResponse;
      pagesFetched += group.result.pagesFetched;
      for (const raw of group.result.items) {
        const item = object(raw, 'Pull request comment');
        combined.push({
          kind: group.kind,
          id: numberValue(item.id),
          node_id: stringValue(item.node_id),
          body: stringValue(item.body),
          state: stringValue(item.state),
          user: compactUser(item.user),
          path: stringValue(item.path),
          line: numberValue(item.line),
          side: stringValue(item.side),
          start_line: numberValue(item.start_line),
          start_side: stringValue(item.start_side),
          commit_id: stringValue(item.commit_id),
          html_url: stringValue(item.html_url),
          created_at: stringValue(item.created_at),
          submitted_at: stringValue(item.submitted_at),
          updated_at: stringValue(item.updated_at),
        });
      }
    }
    combined.sort((left, right) => {
      const leftTime = String(left.created_at ?? left.submitted_at ?? '');
      const rightTime = String(right.created_at ?? right.submitted_at ?? '');
      return leftTime.localeCompare(rightTime);
    });
    const selected = combined.slice(0, maxItems);
    if (!lastResponse) {
      throw new GitHubApiError('internal_error', 'No GitHub comment request was executed.');
    }
    return {
      source: 'github.com',
      operation: 'list_pr_comments',
      repository: `${owner}/${repo}`,
      pull_number: number,
      auth: this.http.tokenProvider.describe('read'),
      returned: selected.length,
      total_collected: combined.length,
      pages_fetched: pagesFetched,
      truncated: combined.length > selected.length,
      items: asJsonValue(selected),
      fetched_at: this.now().toISOString(),
      response: responseMetadata(lastResponse),
    };
  }

  async postReviewComment(input: PostReviewCommentInput): Promise<JsonObject> {
    assertConfirmation(input.confirm);
    const { owner, repo, number } = this.locator(input);
    const body = requiredText(input.body, 'body', 65_535);
    const path = repositoryPath(input.path);
    const side = diffSide(input.side);
    const line = boundedInteger(input.line, input.line, 1, 2_147_483_647, 'line');
    const startLine =
      input.start_line === undefined
        ? undefined
        : boundedInteger(input.start_line, input.start_line, 1, 2_147_483_647, 'start_line');
    const startSide = input.start_side === undefined ? undefined : diffSide(input.start_side);

    const [prResponse, filesResponse] = await Promise.all([
      this.http.getJson(`repos/${owner}/${repo}/pulls/${number}`),
      this.pullRequestFiles(owner, repo, number, this.maxFiles, false),
    ]);
    const pr = object(prResponse.data, 'Pull request detail');
    const head = isJsonObject(pr.head) ? pr.head : {};
    const commitId = stringValue(head.sha);
    if (!commitId) {
      throw new GitHubApiError('invalid_response', 'Pull request response did not include head SHA.');
    }
    const parsedFiles = filesResponse.items.map((item) =>
      parseFileDiff(object(item, 'Pull request file'), false),
    );
    const file = parsedFiles.find((candidate) => candidate.path === path);
    if (!file) {
      throw new GitHubApiError(
        'invalid_diff_location',
        'The requested path is not present in the pull-request diff.',
      );
    }
    validateDiffLocation(file, line, side, startLine, startSide);

    const payload: JsonObject = {
      body,
      commit_id: commitId,
      path,
      line,
      side,
    };
    if (startLine !== undefined && startSide !== undefined) {
      payload.start_line = startLine;
      payload.start_side = startSide;
    }
    const started = Date.now();
    const result = await this.http.postJson(
      `repos/${owner}/${repo}/pulls/${number}/comments`,
      payload,
    );
    const item = object(result.data, 'Created review comment');
    return {
      source: 'github.com',
      operation: 'post_review_comment',
      repository: `${owner}/${repo}`,
      pull_number: number,
      auth: this.http.tokenProvider.describe('write'),
      request_duration_ms: Date.now() - started,
      item: {
        id: numberValue(item.id),
        body: stringValue(item.body),
        path: stringValue(item.path),
        line: numberValue(item.line),
        side: stringValue(item.side),
        start_line: numberValue(item.start_line),
        start_side: stringValue(item.start_side),
        commit_id: stringValue(item.commit_id),
        html_url: stringValue(item.html_url),
        created_at: stringValue(item.created_at),
        user: compactUser(item.user),
      },
      response: responseMetadata(result),
    };
  }

  async submitReview(input: SubmitReviewInput): Promise<JsonObject> {
    assertConfirmation(input.confirm);
    const { owner, repo, number } = this.locator(input);
    const event = reviewEvent(input.event);
    const body = optionalText(input.body, 'body', 65_535);
    if (event === 'REQUEST_CHANGES' && !body) {
      throw new GitHubApiError('invalid_argument', 'REQUEST_CHANGES requires a non-empty body.');
    }
    const payload: JsonObject = { event };
    if (body !== undefined) {
      payload.body = body;
    }
    let path = `repos/${owner}/${repo}/pulls/${number}/reviews`;
    if (input.review_id !== undefined) {
      const reviewId = positiveIdentifier(input.review_id, 'review_id');
      path += `/${reviewId}/events`;
    }
    const started = Date.now();
    const result = await this.http.postJson(path, payload);
    const item = object(result.data, 'Submitted review');
    return {
      source: 'github.com',
      operation: 'submit_review',
      repository: `${owner}/${repo}`,
      pull_number: number,
      auth: this.http.tokenProvider.describe('write'),
      request_duration_ms: Date.now() - started,
      item: {
        id: numberValue(item.id),
        state: stringValue(item.state),
        body: stringValue(item.body),
        html_url: stringValue(item.html_url),
        submitted_at: stringValue(item.submitted_at),
        commit_id: stringValue(item.commit_id),
        user: compactUser(item.user),
      },
      response: responseMetadata(result),
    };
  }

  async addLabels(input: AddLabelsInput): Promise<JsonObject> {
    assertConfirmation(input.confirm);
    const { owner, repo, number } = this.locator(input);
    const selectedLabels = labels(input.labels);
    const started = Date.now();
    const result = await this.http.postJson(
      `repos/${owner}/${repo}/issues/${number}/labels`,
      { labels: asJsonValue(selectedLabels) },
    );
    const created = array(result.data, 'Label response')
      .filter(isJsonObject)
      .map((item) => ({
        id: numberValue(item.id),
        name: stringValue(item.name),
        color: stringValue(item.color),
        description: stringValue(item.description),
      }));
    return {
      source: 'github.com',
      operation: 'add_labels',
      repository: `${owner}/${repo}`,
      pull_number: number,
      auth: this.http.tokenProvider.describe('write'),
      request_duration_ms: Date.now() - started,
      labels: asJsonValue(created),
      response: responseMetadata(result),
    };
  }

  async requestChanges(input: RequestChangesInput): Promise<JsonObject> {
    assertConfirmation(input.confirm);
    const { owner, repo, number } = this.locator(input);
    const body = requiredText(input.body, 'body', 65_535);
    const started = Date.now();
    const result = await this.http.postJson(
      `repos/${owner}/${repo}/pulls/${number}/reviews`,
      { body, event: 'REQUEST_CHANGES' },
    );
    const item = object(result.data, 'Requested-changes review');
    return {
      source: 'github.com',
      operation: 'request_changes',
      repository: `${owner}/${repo}`,
      pull_number: number,
      auth: this.http.tokenProvider.describe('write'),
      request_duration_ms: Date.now() - started,
      item: {
        id: numberValue(item.id),
        state: stringValue(item.state),
        body: stringValue(item.body),
        html_url: stringValue(item.html_url),
        submitted_at: stringValue(item.submitted_at),
        commit_id: stringValue(item.commit_id),
        user: compactUser(item.user),
      },
      response: responseMetadata(result),
    };
  }

  private locator(input: PullRequestLocator): { owner: string; repo: string; number: number } {
    return {
      owner: ownerOrRepository(input.owner, 'owner'),
      repo: ownerOrRepository(input.repo, 'repo'),
      number: pullNumber(input.pull_number),
    };
  }

  private async paginate(
    path: string,
    query: Readonly<Record<string, string | number | boolean | undefined>>,
    maximumItems: number,
  ): Promise<PaginationResult> {
    const items: JsonValue[] = [];
    let lastResponse: HttpResult<JsonValue> | null = null;
    let pagesFetched = 0;
    for (let page = 1; page <= this.maxPages && items.length < maximumItems; page += 1) {
      const perPage = Math.min(100, maximumItems - items.length);
      const response = await this.http.getJson(path, { ...query, per_page: perPage, page });
      lastResponse = response;
      pagesFetched += 1;
      const pageItems = array(response.data, 'GitHub list response');
      items.push(...pageItems.slice(0, maximumItems - items.length));
      if (pageItems.length < perPage) {
        break;
      }
    }
    if (!lastResponse) {
      throw new GitHubApiError('internal_error', 'Pagination did not execute a GitHub request.');
    }
    return { items, lastResponse, pagesFetched };
  }

  private async pullRequestFiles(
    owner: string,
    repo: string,
    number: number,
    maximumFiles: number,
    includePatch: boolean,
  ): Promise<PaginationResult> {
    const result = await this.paginate(
      `repos/${owner}/${repo}/pulls/${number}/files`,
      {},
      Math.min(maximumFiles, this.maxFiles),
    );
    if (!includePatch) {
      // GitHub's files endpoint is still used because it is the authoritative
      // source for commentable diff locations. The caller controls whether raw
      // patch text is returned to the MCP client, not whether it is validated.
    }
    return result;
  }
}
