import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod/v4';

import { GitHubPullRequestClient } from './client.js';
import { runTool } from './tools.js';
import { VERSION } from './version.js';

const READ_ONLY_ANNOTATIONS = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: true,
} as const;

const WRITE_ANNOTATIONS = {
  readOnlyHint: false,
  destructiveHint: false,
  idempotentHint: false,
  openWorldHint: true,
} as const;

const repositoryShape = {
  owner: z.string().trim().min(1).max(100).regex(/^[A-Za-z0-9_.-]+$/),
  repo: z.string().trim().min(1).max(100).regex(/^[A-Za-z0-9_.-]+$/),
} as const;

const pullRequestShape = {
  ...repositoryShape,
  pull_number: z.number().int().min(1),
} as const;

const listPullRequestsSchema = z
  .object({
    ...repositoryShape,
    state: z.enum(['open', 'closed', 'all']).optional().describe('Defaults to open.'),
    sort: z
      .enum(['created', 'updated', 'popularity', 'long-running'])
      .optional()
      .describe('Defaults to updated.'),
    direction: z.enum(['asc', 'desc']).optional().describe('Defaults to desc.'),
    max_items: z.number().int().min(1).max(500).optional().describe('Defaults to 100.'),
  })
  .strict();

const getPullRequestSchema = z.object(pullRequestShape).strict();

const getPullRequestDiffSchema = z
  .object({
    ...pullRequestShape,
    max_files: z.number().int().min(1).max(500).optional().describe('Defaults to 100.'),
    max_lines_per_file: z
      .number()
      .int()
      .min(1)
      .max(2_000)
      .optional()
      .describe('Defaults to 400.'),
    include_patch: z.boolean().optional().describe('Return raw patch text; defaults to false. Parsed hunks are always returned.'),
  })
  .strict();

const listPullRequestCommentsSchema = z
  .object({
    ...pullRequestShape,
    include_issue_comments: z.boolean().optional().describe('Defaults to true.'),
    include_reviews: z.boolean().optional().describe('Defaults to true.'),
    include_inline_comments: z.boolean().optional().describe('Defaults to true.'),
    max_items: z.number().int().min(1).max(500).optional().describe('Defaults to 200.'),
  })
  .strict();

const postReviewCommentSchema = z
  .object({
    ...pullRequestShape,
    body: z.string().trim().min(1).max(65_535),
    path: z.string().trim().min(1).max(1_024),
    line: z.number().int().min(1),
    side: z.enum(['LEFT', 'RIGHT']),
    start_line: z.number().int().min(1).optional(),
    start_side: z.enum(['LEFT', 'RIGHT']).optional(),
    confirm: z.literal(true).describe('Explicit confirmation for this external write.'),
  })
  .strict();

const submitReviewSchema = z
  .object({
    ...pullRequestShape,
    event: z.enum(['APPROVE', 'COMMENT', 'REQUEST_CHANGES']),
    body: z.string().trim().max(65_535).optional(),
    review_id: z.number().int().min(1).optional().describe('Submit an existing pending review.'),
    confirm: z.literal(true).describe('Explicit confirmation for this external write.'),
  })
  .strict();

const addLabelsSchema = z
  .object({
    ...pullRequestShape,
    labels: z.array(z.string().trim().min(1).max(100)).min(1).max(20),
    confirm: z.literal(true).describe('Explicit confirmation for this external write.'),
  })
  .strict();

const requestChangesSchema = z
  .object({
    ...pullRequestShape,
    body: z.string().trim().min(1).max(65_535),
    confirm: z.literal(true).describe('Explicit confirmation for this external write.'),
  })
  .strict();

export function createMcpServer(
  client: GitHubPullRequestClient = new GitHubPullRequestClient(),
): McpServer {
  const server = new McpServer({
    name: 'archimedes-github-pr-mcp',
    version: VERSION,
  });

  server.registerTool(
    'list_prs',
    {
      title: 'List GitHub Pull Requests',
      description:
        'List pull requests with bounded pagination. Public repositories work anonymously; private repositories require read authentication.',
      inputSchema: listPullRequestsSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.listPullRequests(input)),
  );

  server.registerTool(
    'get_pr',
    {
      title: 'Get GitHub Pull Request',
      description:
        'Fetch normalized pull-request metadata, head/base SHAs, labels, review requests, and change counts.',
      inputSchema: getPullRequestSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.getPullRequest(input)),
  );

  server.registerTool(
    'get_pr_diff',
    {
      title: 'Get GitHub Pull Request Diff',
      description:
        'Fetch changed files and parse unified diff hunks into LEFT/RIGHT commentable line numbers. Binary and truncated patches are identified.',
      inputSchema: getPullRequestDiffSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.getPullRequestDiff(input)),
  );

  server.registerTool(
    'list_pr_comments',
    {
      title: 'List GitHub Pull Request Comments',
      description:
        'List and combine issue conversation comments, review summaries, and inline review comments with bounded pagination.',
      inputSchema: listPullRequestCommentsSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.listPullRequestComments(input)),
  );

  server.registerTool(
    'post_review_comment',
    {
      title: 'Post Inline GitHub Review Comment',
      description:
        'Post one immediate inline review comment after validating the path and LEFT/RIGHT line against the current pull-request diff. Requires GITHUB_ALLOW_WRITES=true and confirm=true.',
      inputSchema: postReviewCommentSchema,
      annotations: WRITE_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.postReviewComment(input)),
  );

  server.registerTool(
    'submit_review',
    {
      title: 'Submit GitHub Pull Request Review',
      description:
        'Create a submitted COMMENT/APPROVE/REQUEST_CHANGES review, or submit an existing pending review by review_id. Requires explicit write enablement and confirmation.',
      inputSchema: submitReviewSchema,
      annotations: WRITE_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.submitReview(input)),
  );

  server.registerTool(
    'add_labels',
    {
      title: 'Add Labels to GitHub Pull Request',
      description:
        'Add one or more existing repository labels to the pull request through the issue-label endpoint. Requires explicit write enablement and confirmation.',
      inputSchema: addLabelsSchema,
      annotations: WRITE_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.addLabels(input)),
  );

  server.registerTool(
    'request_changes',
    {
      title: 'Request Changes on GitHub Pull Request',
      description:
        'Submit a REQUEST_CHANGES review with a required explanation. Requires explicit write enablement and confirm=true.',
      inputSchema: requestChangesSchema,
      annotations: WRITE_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.requestChanges(input)),
  );

  server.registerPrompt(
    'review_pr_correctness',
    {
      title: 'Review Pull Request for Correctness',
      description:
        'Opt-in workflow prompt for a read-first correctness review. It never authorizes write tools.',
      argsSchema: {
        owner: z.string().trim().min(1).max(100),
        repo: z.string().trim().min(1).max(100),
        pull_number: z.string().trim().regex(/^\d+$/),
      },
    },
    ({ owner, repo, pull_number }) => ({
      messages: [
        {
          role: 'user',
          content: {
            type: 'text',
            text: [
              `Review ${owner}/${repo} pull request #${pull_number} for correctness.`,
              'Call get_pr, get_pr_diff, and list_pr_comments before reaching a conclusion.',
              'Focus on behavioral regressions, edge cases, error handling, concurrency, tests, and compatibility.',
              'Cite exact file paths and LEFT/RIGHT diff line numbers.',
              'Do not call any write tool unless the user separately and explicitly asks for that exact external action.',
            ].join('\n'),
          },
        },
      ],
    }),
  );

  server.registerPrompt(
    'review_pr_security',
    {
      title: 'Review Pull Request for Security',
      description:
        'Opt-in workflow prompt for a read-first security review. It never authorizes write tools.',
      argsSchema: {
        owner: z.string().trim().min(1).max(100),
        repo: z.string().trim().min(1).max(100),
        pull_number: z.string().trim().regex(/^\d+$/),
      },
    },
    ({ owner, repo, pull_number }) => ({
      messages: [
        {
          role: 'user',
          content: {
            type: 'text',
            text: [
              `Review ${owner}/${repo} pull request #${pull_number} for security risks.`,
              'Call get_pr, get_pr_diff, and list_pr_comments first.',
              'Check trust boundaries, authorization, injection, secret handling, SSRF, path traversal, unsafe retries, race conditions, and supply-chain changes.',
              'Distinguish confirmed findings from hypotheses and cite exact diff locations.',
              'Do not call any write tool unless the user separately and explicitly asks for that exact external action.',
            ].join('\n'),
          },
        },
      ],
    }),
  );

  return server;
}
