import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildConsultationContext,
  createInitialState,
  daysUntil,
  evaluateReadiness,
  normalizeItem,
  rankItems,
  scoreItem,
  summarizeState,
} from '../engine.mjs';

const NOW = new Date('2026-08-09T12:00:00+09:00');

function item(overrides = {}) {
  return normalizeItem({
    id: overrides.id || 'test-item',
    title: 'テスト項目',
    domain: 'development',
    status: 'active',
    nextAction: '30分で試作する',
    metrics: {
      impact: 4,
      urgency: 3,
      evidence: 4,
      compounding: 4,
      interest: 4,
      downside: 2,
      reversibility: 5,
      hours: 1,
      costYen: 0,
    },
    createdAt: '2026-08-09T00:00:00+09:00',
    updatedAt: '2026-08-09T00:00:00+09:00',
    ...overrides,
  }, NOW);
}

test('daysUntil handles today and overdue dates', () => {
  assert.equal(daysUntil('2026-08-09', NOW), 0);
  assert.equal(daysUntil('2026-08-08', NOW), -1);
  assert.equal(daysUntil('', NOW), null);
});

test('ordinary item with next action is ready', () => {
  const readiness = evaluateReadiness(item(), NOW);
  assert.equal(readiness.ready, true);
  assert.equal(readiness.state, 'ready');
});

test('high-stakes item is held without thesis and invalidation', () => {
  const readiness = evaluateReadiness(item({ highStakes: true }), NOW);
  assert.equal(readiness.ready, false);
  assert.equal(readiness.state, 'hold');
  assert.match(readiness.warnings.join(' '), /採用する理由/);
  assert.match(readiness.warnings.join(' '), /撤退/);
});

test('FOMO item is cooled down for 24 hours', () => {
  const readiness = evaluateReadiness(item({ fomo: true }), NOW);
  assert.equal(readiness.state, 'cooldown');
  assert.equal(readiness.ready, false);
});



test('FOMO cooldown uses the moment FOMO was declared, not the original item age', () => {
  const result = evaluateReadiness(item({
    fomo: true,
    createdAt: '2026-07-01T00:00:00.000Z',
    fomoAt: '2026-08-08T09:00:00.000Z',
  }), new Date('2026-08-08T12:00:00.000Z'));
  assert.equal(result.state, 'cooldown');
});

test('strong evidence and lower downside improve wealth-mode score', () => {
  const strong = scoreItem(item(), 'wealth', NOW).score;
  const weak = scoreItem(item({
    metrics: {
      impact: 4,
      urgency: 3,
      evidence: 1,
      compounding: 4,
      interest: 4,
      downside: 5,
      reversibility: 2,
      hours: 12,
      costYen: 500_000,
    },
  }), 'wealth', NOW).score;
  assert.ok(strong > weak, `${strong} should be greater than ${weak}`);
});

test('ready items rank above held items even when raw score is high', () => {
  const ready = item({ id: 'ready', title: '実行できる項目' });
  const held = item({
    id: 'held',
    title: '保留項目',
    highStakes: true,
    metrics: { ...item().metrics, impact: 5, urgency: 5, compounding: 5 },
  });
  const ranked = rankItems([held, ready], 'wealth', NOW);
  assert.equal(ranked[0].item.id, 'ready');
});

test('summary detects overload and stale items', () => {
  const state = createInitialState();
  state.settings.maxActive = 1;
  state.settings.staleDays = 3;
  state.items = [
    item({ id: 'a', updatedAt: '2026-08-01T00:00:00+09:00' }),
    item({ id: 'b', updatedAt: '2026-08-09T00:00:00+09:00' }),
  ];
  const summary = summarizeState(state, NOW);
  assert.equal(summary.overloaded, true);
  assert.equal(summary.staleCount, 1);
});

test('consultation context includes priorities and guardrails', () => {
  const state = createInitialState();
  state.items = [item({ title: '人工生命のMVP' })];
  const context = buildConsultationContext(state, NOW);
  assert.match(context, /人工生命のMVP/);
  assert.match(context, /最大3つ/);
  assert.match(context, /撤退条件/);
});
