import assert from 'node:assert/strict';
import test from 'node:test';

import { ArchimedesApiError } from '../src/errors.js';
import { errorResult, successResult } from '../src/tools.js';

test('returns matching text and structured success content', () => {
  const result = successResult({ source: 'archimedes.market', returned: 0 });
  assert.deepEqual(result.structuredContent, { source: 'archimedes.market', returned: 0 });
  assert.match(result.content[0]?.text ?? '', /archimedes\.market/);
});

test('exposes stable public API errors without causes or stacks', () => {
  const secret = 'DO_NOT_LEAK_THIS_SECRET';
  const result = errorResult(
    new ArchimedesApiError('rate_limited', 'Archimedes public API returned HTTP 429.', {
      status: 429,
      retryable: true,
      rateLimitRemaining: '0',
      cause: new Error(secret),
    }),
  );
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent.error, 'rate_limited');
  assert.doesNotMatch(result.content[0]?.text ?? '', new RegExp(secret));
  assert.doesNotMatch(result.content[0]?.text ?? '', /stack/i);
});

test('redacts unexpected internal errors', () => {
  const result = errorResult(new Error('password=hunter2'));
  assert.equal(result.structuredContent.error, 'internal_error');
  assert.doesNotMatch(result.content[0]?.text ?? '', /hunter2/);
});
