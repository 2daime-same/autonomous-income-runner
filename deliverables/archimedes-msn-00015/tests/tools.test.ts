import assert from 'node:assert/strict';
import test from 'node:test';

import { GitHubApiError } from '../src/errors.js';
import { errorResult, runTool } from '../src/tools.js';

test('returns structured GitHub errors without exposing causes or stacks', async () => {
  const secret = new Error('secret token ghp_private');
  const result = errorResult(
    new GitHubApiError('forbidden', 'GitHub denied this operation.', {
      status: 403,
      requestId: 'REQ-1',
      rateLimit: {
        limit: 5000,
        remaining: 4999,
        used: 1,
        resetAt: '2026-08-01T01:00:00.000Z',
        resource: 'core',
      },
      cause: secret,
    }),
  );
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent.error, 'forbidden');
  assert.doesNotMatch(JSON.stringify(result), /ghp_private|stack/i);
});

test('redacts unexpected failures behind a stable internal error', async () => {
  const result = await runTool(async () => {
    throw new Error('database password=secret');
  });
  assert.equal('isError' in result && result.isError, true);
  assert.equal(result.structuredContent.error, 'internal_error');
  assert.doesNotMatch(JSON.stringify(result), /password|secret/i);
});
