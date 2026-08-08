export const STORAGE_VERSION = 1;

export const MODES = Object.freeze({
  wealth: {
    label: '資産最大化（1〜2年）',
    description: '根拠・下振れ管理・複利性を優先。勢いだけの判断は抑える。',
    weights: { impact: 1.8, urgency: 0.8, evidence: 1.9, compounding: 1.7, interest: 0.5, reversibility: 1.0 },
    penalties: { downside: 1.9, time: 0.65, cost: 0.8 },
  },
  exam: {
    label: '試験・提出集中',
    description: '期限と失点回避を優先。面白さより完了確率を取る。',
    weights: { impact: 1.5, urgency: 2.2, evidence: 1.0, compounding: 0.8, interest: 0.35, reversibility: 0.6 },
    penalties: { downside: 1.4, time: 0.75, cost: 0.35 },
  },
  build: {
    label: '開発スプリント',
    description: '学習・再利用・長期的な技術資産を重視。小さく検証できる案を上げる。',
    weights: { impact: 1.7, urgency: 0.7, evidence: 0.9, compounding: 1.9, interest: 1.3, reversibility: 1.1 },
    penalties: { downside: 1.25, time: 0.8, cost: 0.55 },
  },
  maintenance: {
    label: '回復・整備',
    description: '健康、生活、未処理の詰まりを減らし、次の集中を作る。',
    weights: { impact: 1.2, urgency: 1.1, evidence: 1.0, compounding: 1.1, interest: 1.0, reversibility: 0.8 },
    penalties: { downside: 1.8, time: 0.55, cost: 0.6 },
  },
});

export const DOMAINS = Object.freeze({
  investment: '投資',
  university: '大学',
  development: '開発',
  income: '収益化',
  creatures: '生き物',
  life: '生活',
  other: 'その他',
});

export const STATUSES = Object.freeze({
  active: '進行中',
  waiting: '待ち',
  parked: '保留箱',
  done: '完了',
});

const METRIC_KEYS = ['impact', 'urgency', 'evidence', 'compounding', 'interest', 'reversibility'];
const DAY_MS = 86_400_000;

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function createId(prefix = 'item') {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

export function asNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function normalizeMetric(value, fallback = 3) {
  return clamp(Math.round(asNumber(value, fallback)), 1, 5);
}

export function normalizeItem(raw = {}, now = new Date()) {
  const timestamp = now.toISOString();
  const metrics = raw.metrics ?? {};

  return {
    id: String(raw.id || createId()),
    title: String(raw.title || '').trim(),
    domain: DOMAINS[raw.domain] ? raw.domain : 'other',
    itemType: raw.itemType === 'decision' ? 'decision' : 'task',
    status: STATUSES[raw.status] ? raw.status : 'active',
    nextAction: String(raw.nextAction || '').trim(),
    deadline: raw.deadline ? String(raw.deadline).slice(0, 10) : '',
    notes: String(raw.notes || '').trim(),
    metrics: {
      impact: normalizeMetric(metrics.impact),
      urgency: normalizeMetric(metrics.urgency),
      evidence: normalizeMetric(metrics.evidence),
      compounding: normalizeMetric(metrics.compounding),
      interest: normalizeMetric(metrics.interest),
      downside: normalizeMetric(metrics.downside),
      reversibility: normalizeMetric(metrics.reversibility),
      hours: clamp(asNumber(metrics.hours, 1), 0, 10_000),
      costYen: clamp(asNumber(metrics.costYen, 0), 0, 1_000_000_000),
    },
    highStakes: Boolean(raw.highStakes),
    thesis: String(raw.thesis || '').trim(),
    invalidation: String(raw.invalidation || '').trim(),
    worstCase: String(raw.worstCase || '').trim(),
    reviewDate: raw.reviewDate ? String(raw.reviewDate).slice(0, 10) : '',
    fomo: Boolean(raw.fomo),
    fomoAt: raw.fomoAt || (raw.fomo ? raw.createdAt || timestamp : ''),
    createdAt: raw.createdAt || timestamp,
    updatedAt: raw.updatedAt || timestamp,
    completedAt: raw.completedAt || '',
  };
}

export function createInitialState() {
  return {
    version: STORAGE_VERSION,
    mode: 'wealth',
    settings: {
      focusLimit: 3,
      maxActive: 7,
      staleDays: 7,
    },
    items: [],
  };
}

export function normalizeState(raw = {}) {
  const base = createInitialState();
  return {
    version: STORAGE_VERSION,
    mode: MODES[raw.mode] ? raw.mode : base.mode,
    settings: {
      focusLimit: clamp(Math.round(asNumber(raw.settings?.focusLimit, base.settings.focusLimit)), 1, 5),
      maxActive: clamp(Math.round(asNumber(raw.settings?.maxActive, base.settings.maxActive)), 1, 30),
      staleDays: clamp(Math.round(asNumber(raw.settings?.staleDays, base.settings.staleDays)), 1, 90),
    },
    items: Array.isArray(raw.items) ? raw.items.map((item) => normalizeItem(item)) : [],
  };
}

export function parseLocalDate(dateText) {
  if (!dateText) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateText));
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 23, 59, 59, 999);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function daysUntil(dateText, now = new Date()) {
  const date = parseLocalDate(dateText);
  if (!date) return null;
  const targetDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const currentDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((targetDay.getTime() - currentDay.getTime()) / DAY_MS);
}

export function ageInDays(item, now = new Date()) {
  const updatedAt = new Date(item.updatedAt || item.createdAt || now);
  if (Number.isNaN(updatedAt.getTime())) return 0;
  return Math.max(0, Math.floor((now.getTime() - updatedAt.getTime()) / DAY_MS));
}

export function cooldownUntil(item) {
  const startedAt = new Date(item.fomoAt || item.createdAt);
  if (Number.isNaN(startedAt.getTime())) return null;
  return new Date(startedAt.getTime() + DAY_MS);
}

export function evaluateReadiness(rawItem, now = new Date()) {
  const item = normalizeItem(rawItem, now);
  const warnings = [];

  if (!item.title) {
    return { state: 'invalid', label: '入力不足', ready: false, warnings: ['タイトルがありません。'] };
  }

  if (!item.nextAction) {
    warnings.push('次の一手を、15〜60分で終わる動詞から始まる行動にしてください。');
  }

  if (item.highStakes) {
    if (!item.thesis) warnings.push('高リスク判断なのに、採用する理由が空です。');
    if (!item.invalidation) warnings.push('撤退・見直し条件がありません。');
    if (!item.reviewDate) warnings.push('再評価日がありません。');
    if (!item.worstCase) warnings.push('最悪ケースを言語化していません。');

    if (item.metrics.evidence <= 2 && item.metrics.downside >= 4) {
      warnings.push('根拠が弱く、下振れが大きい組み合わせです。');
    }
  }

  if (item.fomo) {
    const until = cooldownUntil(item);
    if (until && now < until) {
      warnings.push(`FOMO申告があるため、${until.toLocaleString('ja-JP')}まで冷却します。`);
      return { state: 'cooldown', label: '冷却中', ready: false, warnings };
    }
  }

  const hardGate = item.highStakes && (
    !item.thesis ||
    !item.invalidation ||
    !item.reviewDate ||
    (item.metrics.evidence <= 2 && item.metrics.downside >= 4)
  );

  if (hardGate) return { state: 'hold', label: '保留', ready: false, warnings };
  if (!item.nextAction) return { state: 'clarify', label: '具体化', ready: false, warnings };
  return { state: 'ready', label: '実行可', ready: true, warnings };
}

export function deadlineBonus(item, now = new Date()) {
  const days = daysUntil(item.deadline, now);
  if (days === null) return 0;
  if (days < 0) return 18;
  if (days === 0) return 16;
  if (days <= 1) return 13;
  if (days <= 3) return 9;
  if (days <= 7) return 5;
  if (days <= 14) return 2;
  return 0;
}

export function scoreItem(rawItem, modeKey = 'wealth', now = new Date()) {
  const item = normalizeItem(rawItem, now);
  const mode = MODES[modeKey] ?? MODES.wealth;
  const readiness = evaluateReadiness(item, now);

  if (item.status !== 'active') {
    return {
      score: 0,
      readiness,
      positive: 0,
      penalty: 0,
      deadlineBonus: 0,
      explanation: '進行中ではないため順位対象外です。',
    };
  }

  const weightTotal = METRIC_KEYS.reduce((sum, key) => sum + mode.weights[key], 0);
  const weighted = METRIC_KEYS.reduce((sum, key) => {
    const normalized = (item.metrics[key] - 1) / 4;
    return sum + normalized * mode.weights[key];
  }, 0);
  const positive = (weighted / weightTotal) * 100;

  const downsidePenalty = ((item.metrics.downside - 1) / 4) * 18 * mode.penalties.downside;
  const timePenalty = Math.min(Math.log2(item.metrics.hours + 1) / 7, 1) * 13 * mode.penalties.time;
  const costPenalty = Math.min(Math.log10(item.metrics.costYen + 1) / 7, 1) * 12 * mode.penalties.cost;
  const penalty = downsidePenalty + timePenalty + costPenalty;
  const dueBonus = deadlineBonus(item, now);

  let score = clamp(Math.round(positive - penalty + dueBonus), 0, 100);
  if (readiness.state === 'hold') score = Math.min(score, 49);
  if (readiness.state === 'cooldown') score = Math.min(score, 39);
  if (readiness.state === 'clarify') score = Math.min(score, 55);
  if (readiness.state === 'invalid') score = 0;

  return {
    score,
    readiness,
    positive: Math.round(positive),
    penalty: Math.round(penalty),
    deadlineBonus: dueBonus,
    explanation: `価値 ${Math.round(positive)} − 負担 ${Math.round(penalty)} ＋ 期限 ${dueBonus}`,
  };
}

export function rankItems(items, modeKey = 'wealth', now = new Date()) {
  return items
    .map((item) => ({ item: normalizeItem(item, now), result: scoreItem(item, modeKey, now) }))
    .filter(({ item }) => item.status === 'active')
    .sort((a, b) => {
      if (a.result.readiness.ready !== b.result.readiness.ready) return a.result.readiness.ready ? -1 : 1;
      if (b.result.score !== a.result.score) return b.result.score - a.result.score;
      const aDeadline = parseLocalDate(a.item.deadline)?.getTime() ?? Number.POSITIVE_INFINITY;
      const bDeadline = parseLocalDate(b.item.deadline)?.getTime() ?? Number.POSITIVE_INFINITY;
      if (aDeadline !== bDeadline) return aDeadline - bDeadline;
      return a.item.createdAt.localeCompare(b.item.createdAt);
    });
}

export function summarizeState(state, now = new Date()) {
  const normalized = normalizeState(state);
  const ranked = rankItems(normalized.items, normalized.mode, now);
  const active = normalized.items.filter((item) => item.status === 'active');
  const done = normalized.items.filter((item) => item.status === 'done');
  const holds = ranked.filter(({ result }) => !result.readiness.ready);
  const stale = active.filter((item) => ageInDays(item, now) >= normalized.settings.staleDays);
  const weekAgo = new Date(now.getTime() - 7 * DAY_MS);
  const completedThisWeek = done.filter((item) => {
    const completed = new Date(item.completedAt || item.updatedAt);
    return !Number.isNaN(completed.getTime()) && completed >= weekAgo;
  });

  const domainCounts = Object.fromEntries(Object.keys(DOMAINS).map((key) => [key, 0]));
  active.forEach((item) => { domainCounts[item.domain] = (domainCounts[item.domain] || 0) + 1; });

  return {
    ranked,
    activeCount: active.length,
    doneCount: done.length,
    holdCount: holds.length,
    staleCount: stale.length,
    stale,
    completedThisWeek,
    domainCounts,
    overloaded: active.length > normalized.settings.maxActive,
  };
}

function formatDeadline(dateText, now) {
  const days = daysUntil(dateText, now);
  if (days === null) return '期限なし';
  if (days < 0) return `${Math.abs(days)}日超過`;
  if (days === 0) return '今日';
  return `あと${days}日`;
}

export function buildConsultationContext(state, now = new Date()) {
  const normalized = normalizeState(state);
  const summary = summarizeState(normalized, now);
  const mode = MODES[normalized.mode];
  const focus = summary.ranked.slice(0, normalized.settings.focusLimit);
  const holds = summary.ranked.filter(({ result }) => !result.readiness.ready).slice(0, 5);

  const lines = [
    '# 現在の判断コンテキスト',
    '',
    `- モード: ${mode.label}`,
    `- 進行中: ${summary.activeCount}件 / 上限${normalized.settings.maxActive}件`,
    `- 保留ゲート: ${summary.holdCount}件`,
    `- ${normalized.settings.staleDays}日以上更新なし: ${summary.staleCount}件`,
    '',
    '## 優先候補',
  ];

  if (focus.length === 0) {
    lines.push('- なし');
  } else {
    focus.forEach(({ item, result }, index) => {
      lines.push(`${index + 1}. **${item.title}** [${DOMAINS[item.domain]} / ${result.score}点 / ${result.readiness.label}]`);
      lines.push(`   - 次の一手: ${item.nextAction || '未設定'}`);
      lines.push(`   - 期限: ${formatDeadline(item.deadline, now)}`);
      if (item.highStakes) {
        lines.push(`   - 理由: ${item.thesis || '未設定'}`);
        lines.push(`   - 見直し条件: ${item.invalidation || '未設定'}`);
        lines.push(`   - 最悪ケース: ${item.worstCase || '未設定'}`);
        lines.push(`   - 再評価日: ${item.reviewDate || '未設定'}`);
      }
      if (item.notes) lines.push(`   - 補足: ${item.notes}`);
    });
  }

  lines.push('', '## 止まっている判断');
  if (holds.length === 0) {
    lines.push('- なし');
  } else {
    holds.forEach(({ item, result }) => {
      lines.push(`- **${item.title}**: ${result.readiness.warnings.join(' / ')}`);
    });
  }

  lines.push(
    '',
    '## 相談したいこと',
    '上記を前提に、今日やるべきことを最大3つに絞り、捨てる・保留する候補も明示してください。高リスク判断は、根拠の弱点と撤退条件を優先して検討してください。',
  );

  return lines.join('\n');
}
