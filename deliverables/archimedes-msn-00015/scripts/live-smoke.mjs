#!/usr/bin/env node
import { GitHubPullRequestClient } from '../dist/client.js';
import { optionsFromEnvironment } from '../dist/config.js';

const owner = String(process.env.GITHUB_SMOKE_OWNER ?? '').trim();
const repo = String(process.env.GITHUB_SMOKE_REPO ?? '').trim();
if (!owner || !repo) {
  throw new Error('GITHUB_SMOKE_OWNER and GITHUB_SMOKE_REPO are required.');
}

const client = new GitHubPullRequestClient(optionsFromEnvironment());
let pullNumber = Number(process.env.GITHUB_SMOKE_PR ?? '0');
const list = await client.listPullRequests({ owner, repo, state: 'open', max_items: 5 });
if (!Number.isSafeInteger(pullNumber) || pullNumber < 1) {
  const first = Array.isArray(list.items) ? list.items[0] : undefined;
  pullNumber = Number(first && typeof first === 'object' ? first.number : 0);
}
if (!Number.isSafeInteger(pullNumber) || pullNumber < 1) {
  throw new Error(`No open pull request was available for ${owner}/${repo}.`);
}

const pr = await client.getPullRequest({ owner, repo, pull_number: pullNumber });
const diff = await client.getPullRequestDiff({
  owner,
  repo,
  pull_number: pullNumber,
  max_files: 20,
  max_lines_per_file: 100,
  include_patch: false,
});
const comments = await client.listPullRequestComments({
  owner,
  repo,
  pull_number: pullNumber,
  max_items: 50,
});

const evidence = {
  ok: true,
  mode: 'read-only',
  writes_performed: [],
  repository: `${owner}/${repo}`,
  pull_number: pullNumber,
  list_returned: list.returned,
  pr_title: pr.item && typeof pr.item === 'object' ? pr.item.title : null,
  diff_files_returned: diff.returned_files,
  comments_returned: comments.returned,
  auth: pr.auth,
  generated_at: new Date().toISOString(),
};
process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
