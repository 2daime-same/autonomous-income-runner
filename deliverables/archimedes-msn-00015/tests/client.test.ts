import assert from 'node:assert/strict';
import test from 'node:test';

import { GitHubPullRequestClient } from '../src/client.js';
import { GitHubApiError } from '../src/errors.js';
import { SAMPLE_PATCH, StaticTokenProvider, sendJson, startTestServer } from './helpers.js';

async function readBody(request: import('node:http').IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown;
}

function pullRequest(number: number) {
  return {
    number,
    title: `PR ${number}`,
    state: 'open',
    draft: false,
    locked: false,
    html_url: `https://github.com/example/project/pull/${number}`,
    url: `https://api.github.com/repos/example/project/pulls/${number}`,
    user: { login: 'contributor', id: 1, type: 'User', html_url: 'https://github.com/contributor' },
    head: { ref: `feature-${number}`, sha: 'abc123', repo: { full_name: 'example/project' } },
    base: { ref: 'main', sha: 'def456', repo: { full_name: 'example/project' } },
    labels: [{ name: 'ready', color: '00ff00' }],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:01:00Z',
  };
}

test('lists more than 100 pull requests with bounded pagination', async () => {
  const requestedPages: number[] = [];
  const api = await startTestServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const page = Number(url.searchParams.get('page') ?? '1');
    requestedPages.push(page);
    const start = (page - 1) * 100 + 1;
    const end = Math.min(125, start + 99);
    const items = start > 125 ? [] : Array.from({ length: end - start + 1 }, (_, index) => pullRequest(start + index));
    sendJson(response, items);
  });
  const client = new GitHubPullRequestClient({
    baseUrl: api.baseUrl,
    maxPages: 5,
    tokenProvider: new StaticTokenProvider(),
  });
  try {
    const result = await client.listPullRequests({ owner: 'example', repo: 'project', max_items: 125 });
    assert.equal(result.returned, 125);
    assert.equal(result.pages_fetched, 2);
    assert.deepEqual(requestedPages, [1, 2]);
  } finally {
    await api.close();
  }
});

test('reads PR metadata, parsed diffs, and all comment surfaces', async () => {
  const api = await startTestServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    if (url.pathname === '/repos/example/project/pulls/7') {
      sendJson(response, {
        ...pullRequest(7),
        body: 'Implementation details',
        mergeable: true,
        mergeable_state: 'clean',
        merged: false,
        commits: 2,
        additions: 2,
        deletions: 1,
        changed_files: 1,
        comments: 1,
        review_comments: 1,
        requested_reviewers: [{ login: 'reviewer', id: 2, type: 'User' }],
      });
      return;
    }
    if (url.pathname === '/repos/example/project/pulls/7/files') {
      sendJson(response, [
        {
          filename: 'src/example.ts',
          status: 'modified',
          additions: 2,
          deletions: 1,
          changes: 3,
          patch: SAMPLE_PATCH,
        },
      ]);
      return;
    }
    if (url.pathname === '/repos/example/project/issues/7/comments') {
      sendJson(response, [
        {
          id: 10,
          body: 'conversation',
          user: { login: 'alice' },
          html_url: 'https://github.com/example/project/pull/7#issuecomment-10',
          created_at: '2026-08-01T00:01:00Z',
        },
      ]);
      return;
    }
    if (url.pathname === '/repos/example/project/pulls/7/reviews') {
      sendJson(response, [
        {
          id: 11,
          body: 'review summary',
          state: 'COMMENTED',
          user: { login: 'bob' },
          html_url: 'https://github.com/example/project/pull/7#pullrequestreview-11',
          submitted_at: '2026-08-01T00:02:00Z',
        },
      ]);
      return;
    }
    if (url.pathname === '/repos/example/project/pulls/7/comments') {
      sendJson(response, [
        {
          id: 12,
          body: 'inline',
          path: 'src/example.ts',
          line: 2,
          side: 'RIGHT',
          user: { login: 'carol' },
          html_url: 'https://github.com/example/project/pull/7#discussion_r12',
          created_at: '2026-08-01T00:03:00Z',
        },
      ]);
      return;
    }
    sendJson(response, { message: 'not found' }, 404);
  });
  const client = new GitHubPullRequestClient({
    baseUrl: api.baseUrl,
    tokenProvider: new StaticTokenProvider(),
  });
  try {
    const pr = await client.getPullRequest({ owner: 'example', repo: 'project', pull_number: 7 });
    assert.equal((pr.item as { mergeable: boolean }).mergeable, true);

    const diff = await client.getPullRequestDiff({
      owner: 'example',
      repo: 'project',
      pull_number: 7,
    });
    const files = diff.files as Array<{ path: string; hunks: Array<{ lines: unknown[] }> }>;
    assert.equal(files[0]?.path, 'src/example.ts');
    assert.equal(files[0]?.hunks[0]?.lines.length, 5);

    const comments = await client.listPullRequestComments({
      owner: 'example',
      repo: 'project',
      pull_number: 7,
    });
    assert.equal(comments.returned, 3);
    assert.deepEqual(
      (comments.items as Array<{ kind: string }>).map((item) => item.kind),
      ['issue_comment', 'review', 'inline_review_comment'],
    );
  } finally {
    await api.close();
  }
});

test('performs all four write operations only with explicit confirmation', async () => {
  const writes: Array<{ path: string; body: unknown }> = [];
  const api = await startTestServer(async (request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    if (request.method === 'GET' && url.pathname === '/repos/example/project/pulls/7') {
      sendJson(response, { ...pullRequest(7), head: { sha: 'head-sha' } });
      return;
    }
    if (request.method === 'GET' && url.pathname === '/repos/example/project/pulls/7/files') {
      sendJson(response, [
        {
          filename: 'src/example.ts',
          status: 'modified',
          additions: 2,
          deletions: 1,
          changes: 3,
          patch: SAMPLE_PATCH,
        },
      ]);
      return;
    }
    if (request.method === 'POST') {
      const body = await readBody(request);
      writes.push({ path: url.pathname, body });
      if (url.pathname.endsWith('/comments')) {
        sendJson(response, {
          id: 20,
          body: 'Please handle this edge case.',
          path: 'src/example.ts',
          line: 2,
          side: 'RIGHT',
          commit_id: 'head-sha',
          html_url: 'https://github.com/example/project/pull/7#discussion_r20',
          created_at: '2026-08-01T00:04:00Z',
          user: { login: 'reviewer' },
        }, 201);
        return;
      }
      if (url.pathname.endsWith('/labels')) {
        sendJson(response, [{ id: 21, name: 'needs-work', color: 'ff0000' }]);
        return;
      }
      sendJson(response, {
        id: 22,
        state: 'CHANGES_REQUESTED',
        body: 'Please add a regression test.',
        html_url: 'https://github.com/example/project/pull/7#pullrequestreview-22',
        submitted_at: '2026-08-01T00:05:00Z',
        user: { login: 'reviewer' },
      }, 200);
      return;
    }
    sendJson(response, { message: 'not found' }, 404);
  });
  const client = new GitHubPullRequestClient({
    baseUrl: api.baseUrl,
    tokenProvider: new StaticTokenProvider(true),
  });
  try {
    await assert.rejects(
      () =>
        client.requestChanges({
          owner: 'example',
          repo: 'project',
          pull_number: 7,
          body: 'No confirmation',
          confirm: false,
        }),
      (error: unknown) => error instanceof GitHubApiError && error.code === 'confirmation_required',
    );

    const comment = await client.postReviewComment({
      owner: 'example',
      repo: 'project',
      pull_number: 7,
      body: 'Please handle this edge case.',
      path: 'src/example.ts',
      line: 2,
      side: 'RIGHT',
      confirm: true,
    });
    assert.equal((comment.item as { id: number }).id, 20);

    await client.submitReview({
      owner: 'example',
      repo: 'project',
      pull_number: 7,
      event: 'COMMENT',
      body: 'Overall review summary.',
      confirm: true,
    });
    await client.addLabels({
      owner: 'example',
      repo: 'project',
      pull_number: 7,
      labels: ['needs-work'],
      confirm: true,
    });
    await client.requestChanges({
      owner: 'example',
      repo: 'project',
      pull_number: 7,
      body: 'Please add a regression test.',
      confirm: true,
    });

    assert.deepEqual(
      writes.map((write) => write.path),
      [
        '/repos/example/project/pulls/7/comments',
        '/repos/example/project/pulls/7/reviews',
        '/repos/example/project/issues/7/labels',
        '/repos/example/project/pulls/7/reviews',
      ],
    );
    assert.deepEqual(writes[0]?.body, {
      body: 'Please handle this edge case.',
      commit_id: 'head-sha',
      path: 'src/example.ts',
      line: 2,
      side: 'RIGHT',
    });
  } finally {
    await api.close();
  }
});
