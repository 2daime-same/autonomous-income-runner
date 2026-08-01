import assert from 'node:assert/strict';
import test from 'node:test';

import { compactFileDiff, parseFileDiff, parsePatch, validateDiffLocation } from '../src/diff.js';
import { GitHubApiError } from '../src/errors.js';
import { SAMPLE_PATCH } from './helpers.js';

test('parses unified diff hunks into LEFT and RIGHT line coordinates', () => {
  const hunks = parsePatch(SAMPLE_PATCH);
  assert.equal(hunks.length, 1);
  const lines = hunks[0]?.lines ?? [];
  assert.deepEqual(
    lines.map((line) => [line.kind, line.oldLine, line.newLine, line.text]),
    [
      ['context', 1, 1, 'const value = 1;'],
      ['deletion', 2, null, 'const oldName = true;'],
      ['addition', null, 2, 'const newName = true;'],
      ['addition', null, 3, 'const added = 2;'],
      ['context', 3, 4, 'return value;'],
    ],
  );
});

test('validates single and multi-line inline comment locations', () => {
  const file = parseFileDiff({
    filename: 'src/example.ts',
    status: 'modified',
    additions: 2,
    deletions: 1,
    changes: 3,
    patch: SAMPLE_PATCH,
  });
  assert.doesNotThrow(() => validateDiffLocation(file, 2, 'LEFT'));
  assert.doesNotThrow(() => validateDiffLocation(file, 3, 'RIGHT', 2, 'RIGHT'));
  assert.throws(() => validateDiffLocation(file, 99, 'RIGHT'), (error: unknown) => {
    return error instanceof GitHubApiError && error.code === 'invalid_diff_location';
  });
  assert.throws(() => validateDiffLocation(file, 3, 'RIGHT', 2, 'LEFT'), GitHubApiError);
});

test('identifies binary patches and bounds returned line evidence', () => {
  const binary = parseFileDiff({ filename: 'image.png', status: 'added', changes: 0 });
  assert.equal(binary.binary, true);
  assert.equal(binary.patchUnavailable, true);
  assert.equal(binary.hunks.length, 0);

  const file = parseFileDiff({ filename: 'src/example.ts', status: 'modified', patch: SAMPLE_PATCH });
  const compact = compactFileDiff(file, 2);
  assert.equal(compact.hunks[0]?.lines.length, 2);
  assert.equal(compact.patchTruncated, true);
});
