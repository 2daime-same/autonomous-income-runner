import assert from 'node:assert/strict';
import test from 'node:test';

import { ArchimedesApiError } from '../src/errors.js';
import {
  boundedInteger,
  normalizeBaseUrl,
  optionalText,
  publicIdentifier,
  retryAfterMilliseconds,
} from '../src/validation.js';

test('normalizes secure and loopback base URLs', () => {
  assert.equal(normalizeBaseUrl('https://archimedes.market').href, 'https://archimedes.market/');
  assert.equal(normalizeBaseUrl('http://127.0.0.1:8080/api').href, 'http://127.0.0.1:8080/api/');
});

test('rejects unsafe base URLs', () => {
  for (const value of [
    'http://archimedes.market',
    'https://user:secret@archimedes.market',
    'https://archimedes.market?token=secret',
    'file:///tmp/data',
  ]) {
    assert.throws(() => normalizeBaseUrl(value), ArchimedesApiError);
  }
});

test('validates bounded values and identifiers', () => {
  assert.equal(boundedInteger(undefined, 20, 1, 50), 20);
  assert.equal(boundedInteger(50, 20, 1, 50), 50);
  assert.throws(() => boundedInteger(0, 20, 1, 50), /between 1 and 50/);
  assert.equal(optionalText('  Python  ', 'query', 20), 'Python');
  assert.equal(optionalText('   ', 'query', 20), undefined);
  assert.throws(() => optionalText('x'.repeat(21), 'query', 20), /at most 20/);
  assert.equal(
    publicIdentifier('5586f0c8-cde1-416c-ac28-d85bc6a264f0', 'bounty_id'),
    '5586f0c8-cde1-416c-ac28-d85bc6a264f0',
  );
  assert.throws(() => publicIdentifier('../../etc/passwd', 'asset_id'), /letters, digits/);
});

test('parses bounded Retry-After values', () => {
  const now = new Date('2026-07-31T00:00:00.000Z');
  assert.equal(retryAfterMilliseconds('2', now), 2_000);
  assert.equal(retryAfterMilliseconds('120', now), 5_000);
  assert.equal(retryAfterMilliseconds('Fri, 31 Jul 2026 00:00:03 GMT', now), 3_000);
  assert.equal(retryAfterMilliseconds('invalid', now), null);
});
