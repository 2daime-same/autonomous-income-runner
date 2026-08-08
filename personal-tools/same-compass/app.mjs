import {
  DOMAINS,
  MODES,
  STATUSES,
  buildConsultationContext,
  createInitialState,
  daysUntil,
  normalizeItem,
  normalizeState,
  rankItems,
  scoreItem,
  summarizeState,
} from './engine.mjs';

const STORAGE_KEY = 'same-compass.state.v1';
const metricKeys = ['impact', 'urgency', 'evidence', 'compounding', 'interest', 'downside', 'reversibility'];

const ITEM_TEMPLATES = Object.freeze({
  investment: {
    label: '投資判断',
    titlePlaceholder: '例：○○の決算を跨ぐか決める',
    domain: 'investment',
    itemType: 'decision',
    nextAction: '一次資料・市場予想・下振れ条件を確認し、買う／待つ／売る条件を5行で書く',
    metrics: { impact: 5, urgency: 3, evidence: 3, compounding: 3, interest: 4, downside: 4, reversibility: 2, hours: 1, costYen: 0 },
    highStakes: true,
  },
  university: {
    label: '試験・提出',
    titlePlaceholder: '例：ファイナンス試験の第3章を固める',
    domain: 'university',
    itemType: 'task',
    nextAction: '試験範囲と採点基準を確認し、25分で例題を3問解く',
    metrics: { impact: 4, urgency: 5, evidence: 5, compounding: 3, interest: 2, downside: 2, reversibility: 5, hours: 0.5, costYen: 0 },
    highStakes: false,
  },
  development: {
    label: '開発実験',
    titlePlaceholder: '例：人工生命の最小実験を作る',
    domain: 'development',
    itemType: 'task',
    nextAction: '最小検証を1つ定義し、動く試作品と失敗条件を作る',
    metrics: { impact: 4, urgency: 2, evidence: 2, compounding: 5, interest: 5, downside: 2, reversibility: 5, hours: 2, costYen: 0 },
    highStakes: false,
  },
  income: {
    label: '収益案件',
    titlePlaceholder: '例：応募できる有償案件を1件進める',
    domain: 'income',
    itemType: 'task',
    nextAction: '報酬・締切・受注条件を確認し、応募または納品の最小成果物を1つ作る',
    metrics: { impact: 4, urgency: 4, evidence: 4, compounding: 4, interest: 3, downside: 2, reversibility: 4, hours: 1, costYen: 0 },
    highStakes: false,
  },
  creatures: {
    label: '生き物・予定',
    titlePlaceholder: '例：近場の爬虫類イベントへ行くか決める',
    domain: 'creatures',
    itemType: 'decision',
    nextAction: '公式の募集・開催情報、移動時間、費用を確認し、行く／応募する条件を決める',
    metrics: { impact: 3, urgency: 3, evidence: 4, compounding: 2, interest: 5, downside: 1, reversibility: 5, hours: 0.5, costYen: 0 },
    highStakes: false,
  },
});

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const dom = {
  modeSelect: $('#modeSelect'),
  modeDescription: $('#modeDescription'),
  tabs: $$('.tab-button'),
  templateButtons: $$('[data-template]'),
  panels: $$('.panel'),
  quickAddButton: $('#quickAddButton'),
  queueAddButton: $('#queueAddButton'),
  alertArea: $('#alertArea'),
  topTitle: $('#topTitle'),
  topAction: $('#topAction'),
  activeCount: $('#activeCount'),
  activeLimit: $('#activeLimit'),
  holdCount: $('#holdCount'),
  staleCount: $('#staleCount'),
  staleLabel: $('#staleLabel'),
  focusCounter: $('#focusCounter'),
  focusList: $('#focusList'),
  domainLoad: $('#domainLoad'),
  gateList: $('#gateList'),
  searchInput: $('#searchInput'),
  domainFilter: $('#domainFilter'),
  statusFilter: $('#statusFilter'),
  queueList: $('#queueList'),
  itemForm: $('#itemForm'),
  itemId: $('#itemId'),
  editorTitle: $('#editorTitle'),
  resetFormButton: $('#resetFormButton'),
  cancelEditButton: $('#cancelEditButton'),
  titleInput: $('#titleInput'),
  domainInput: $('#domainInput'),
  itemTypeInput: $('#itemTypeInput'),
  nextActionInput: $('#nextActionInput'),
  deadlineInput: $('#deadlineInput'),
  statusInput: $('#statusInput'),
  hoursInput: $('#hoursInput'),
  costInput: $('#costInput'),
  highStakesInput: $('#highStakesInput'),
  guardrailFields: $('#guardrailFields'),
  thesisInput: $('#thesisInput'),
  invalidationInput: $('#invalidationInput'),
  worstCaseInput: $('#worstCaseInput'),
  reviewDateInput: $('#reviewDateInput'),
  fomoInput: $('#fomoInput'),
  notesInput: $('#notesInput'),
  liveScore: $('#liveScore'),
  liveScoreText: $('#liveScoreText'),
  formMessages: $('#formMessages'),
  contextOutput: $('#contextOutput'),
  copyContextButton: $('#copyContextButton'),
  focusLimitInput: $('#focusLimitInput'),
  maxActiveInput: $('#maxActiveInput'),
  staleDaysInput: $('#staleDaysInput'),
  saveSettingsButton: $('#saveSettingsButton'),
  completedList: $('#completedList'),
  exportButton: $('#exportButton'),
  importInput: $('#importInput'),
  clearButton: $('#clearButton'),
  toast: $('#toast'),
  focusItemTemplate: $('#focusItemTemplate'),
  queueItemTemplate: $('#queueItemTemplate'),
};

metricKeys.forEach((key) => {
  dom[`${key}Input`] = $(`#${key}Input`);
  dom[`${key}Output`] = $(`#${key}Output`);
});

let state = loadState();
let toastTimer = null;

function loadState() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? normalizeState(JSON.parse(stored)) : createInitialState();
  } catch (error) {
    console.warn('Stored state could not be read.', error);
    return createInitialState();
  }
}

function persistState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    console.error('State could not be stored.', error);
    showToast('保存に失敗しました。ブラウザの空き容量を確認してください。', true);
  }
}

function commitState(nextState, toastMessage = '') {
  state = normalizeState(nextState);
  persistState();
  renderAll();
  if (toastMessage) showToast(toastMessage);
}

function initializeSelects() {
  dom.modeSelect.replaceChildren(...Object.entries(MODES).map(([value, mode]) => option(value, mode.label)));
  dom.domainInput.replaceChildren(...Object.entries(DOMAINS).map(([value, label]) => option(value, label)));
  dom.domainFilter.append(...Object.entries(DOMAINS).map(([value, label]) => option(value, label)));
  dom.statusInput.replaceChildren(...Object.entries(STATUSES).map(([value, label]) => option(value, label)));
  dom.statusFilter.append(...Object.entries(STATUSES).map(([value, label]) => option(value, label)));
}

function option(value, label) {
  const element = document.createElement('option');
  element.value = value;
  element.textContent = label;
  return element;
}

function switchTab(name, focus = false) {
  dom.tabs.forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', String(active));
  });
  dom.panels.forEach((panel) => {
    const active = panel.dataset.panel === name;
    panel.hidden = !active;
    panel.classList.toggle('is-active', active);
  });
  if (focus) {
    const panel = $(`[data-panel="${name}"]`);
    panel?.querySelector('h2')?.focus?.({ preventScroll: true });
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetForm() {
  dom.itemForm.reset();
  dom.titleInput.placeholder = '例：決算前の保有方針を決める';
  dom.itemId.value = '';
  dom.domainInput.value = 'other';
  dom.itemTypeInput.value = 'task';
  dom.statusInput.value = 'active';
  dom.hoursInput.value = '1';
  dom.costInput.value = '0';
  metricKeys.forEach((key) => {
    dom[`${key}Input`].value = '3';
    dom[`${key}Output`].value = '3';
  });
  dom.guardrailFields.hidden = true;
  dom.editorTitle.textContent = '項目を追加';
  dom.cancelEditButton.hidden = true;
  dom.formMessages.replaceChildren();
  updateLiveScore();
}

function applyTemplate(key) {
  const template = ITEM_TEMPLATES[key];
  if (!template) return;

  resetForm();
  dom.titleInput.placeholder = template.titlePlaceholder;
  dom.domainInput.value = template.domain;
  dom.itemTypeInput.value = template.itemType;
  dom.nextActionInput.value = template.nextAction;
  metricKeys.forEach((metric) => {
    dom[`${metric}Input`].value = String(template.metrics[metric]);
    dom[`${metric}Output`].value = String(template.metrics[metric]);
  });
  dom.hoursInput.value = String(template.metrics.hours);
  dom.costInput.value = String(template.metrics.costYen);
  dom.highStakesInput.checked = template.highStakes;
  dom.guardrailFields.hidden = !template.highStakes;
  updateLiveScore();
  dom.titleInput.focus();
  showToast(`「${template.label}」の型を入れました。`);
}

function formItem() {
  const existing = state.items.find((item) => item.id === dom.itemId.value);
  const now = new Date().toISOString();
  const highStakes = dom.highStakesInput.checked;
  const fomo = highStakes && dom.fomoInput.checked;
  return normalizeItem({
    id: existing?.id,
    title: dom.titleInput.value,
    domain: dom.domainInput.value,
    itemType: dom.itemTypeInput.value,
    status: dom.statusInput.value,
    nextAction: dom.nextActionInput.value,
    deadline: dom.deadlineInput.value,
    notes: dom.notesInput.value,
    metrics: {
      ...Object.fromEntries(metricKeys.map((key) => [key, dom[`${key}Input`].value])),
      hours: dom.hoursInput.value,
      costYen: dom.costInput.value,
    },
    highStakes,
    thesis: dom.thesisInput.value,
    invalidation: dom.invalidationInput.value,
    worstCase: dom.worstCaseInput.value,
    reviewDate: dom.reviewDateInput.value,
    fomo,
    fomoAt: fomo
      ? (existing?.fomo ? existing.fomoAt || existing.createdAt || now : now)
      : '',
    createdAt: existing?.createdAt || now,
    updatedAt: now,
    completedAt: dom.statusInput.value === 'done'
      ? existing?.completedAt || now
      : '',
  });
}

function editItem(id) {
  const item = state.items.find((candidate) => candidate.id === id);
  if (!item) return;

  dom.itemId.value = item.id;
  dom.titleInput.value = item.title;
  dom.domainInput.value = item.domain;
  dom.itemTypeInput.value = item.itemType;
  dom.statusInput.value = item.status;
  dom.nextActionInput.value = item.nextAction;
  dom.deadlineInput.value = item.deadline;
  dom.notesInput.value = item.notes;
  metricKeys.forEach((key) => {
    dom[`${key}Input`].value = String(item.metrics[key]);
    dom[`${key}Output`].value = String(item.metrics[key]);
  });
  dom.hoursInput.value = String(item.metrics.hours);
  dom.costInput.value = String(item.metrics.costYen);
  dom.highStakesInput.checked = item.highStakes;
  dom.guardrailFields.hidden = !item.highStakes;
  dom.thesisInput.value = item.thesis;
  dom.invalidationInput.value = item.invalidation;
  dom.worstCaseInput.value = item.worstCase;
  dom.reviewDateInput.value = item.reviewDate;
  dom.fomoInput.checked = item.fomo;
  dom.editorTitle.textContent = '項目を編集';
  dom.cancelEditButton.hidden = false;
  dom.formMessages.replaceChildren();
  updateLiveScore();
  switchTab('editor');
  dom.titleInput.focus();
}

function validateForm(item) {
  const messages = [];
  if (!item.title) messages.push('タイトルは必須です。');
  if (item.title.length > 120) messages.push('タイトルが長すぎます。');
  if (item.metrics.hours < 0) messages.push('必要時間は0以上にしてください。');
  if (item.metrics.costYen < 0) messages.push('必要金額は0以上にしてください。');
  return messages;
}

function handleFormSubmit(event) {
  event.preventDefault();
  const item = formItem();
  const errors = validateForm(item);
  dom.formMessages.replaceChildren(...errors.map((message) => {
    const element = document.createElement('div');
    element.className = 'form-error';
    element.textContent = message;
    return element;
  }));
  if (errors.length) return;

  const index = state.items.findIndex((candidate) => candidate.id === item.id);
  const items = [...state.items];
  if (index >= 0) items[index] = item;
  else items.push(item);

  commitState({ ...state, items }, index >= 0 ? '更新しました。' : '追加しました。');
  resetForm();
  switchTab('dashboard');
}

function updateLiveScore() {
  metricKeys.forEach((key) => {
    dom[`${key}Output`].value = dom[`${key}Input`].value;
  });
  dom.guardrailFields.hidden = !dom.highStakesInput.checked;

  const item = formItem();
  if (!item.title) {
    dom.liveScore.textContent = '--';
    dom.liveScoreText.textContent = 'タイトルと評価を入力すると、現在のモードでの優先度を計算します。';
    return;
  }

  const result = scoreItem(item, state.mode);
  dom.liveScore.textContent = `${result.score}`;
  const warning = result.readiness.warnings[0] ? ` / ${result.readiness.warnings[0]}` : '';
  dom.liveScoreText.textContent = `${result.explanation} / ${result.readiness.label}${warning}`;
}

function updateItemStatus(id, targetStatus) {
  const now = new Date().toISOString();
  const items = state.items.map((item) => item.id === id ? normalizeItem({
    ...item,
    status: targetStatus,
    updatedAt: now,
    completedAt: targetStatus === 'done' ? item.completedAt || now : '',
  }) : item);
  commitState({ ...state, items }, targetStatus === 'done' ? '完了にしました。' : '状態を更新しました。');
}

function deleteItem(id) {
  const item = state.items.find((candidate) => candidate.id === id);
  if (!item) return;
  if (!window.confirm(`「${item.title}」を削除します。元に戻せません。`)) return;
  commitState({ ...state, items: state.items.filter((candidate) => candidate.id !== id) }, '削除しました。');
}

function handleItemAction(action, id) {
  const item = state.items.find((candidate) => candidate.id === id);
  if (!item) return;
  if (action === 'edit') editItem(id);
  if (action === 'done') updateItemStatus(id, 'done');
  if (action === 'toggle-done') updateItemStatus(id, item.status === 'done' ? 'active' : 'done');
  if (action === 'park') updateItemStatus(id, item.status === 'parked' ? 'active' : 'parked');
  if (action === 'delete') deleteItem(id);
}

function renderAll() {
  dom.modeSelect.value = state.mode;
  dom.modeDescription.textContent = MODES[state.mode].description;
  renderDashboard();
  renderQueue();
  renderReview();
  updateLiveScore();
}

function renderDashboard() {
  const summary = summarizeState(state);
  const focusItems = summary.ranked.filter(({ result }) => result.readiness.ready).slice(0, state.settings.focusLimit);
  const top = focusItems[0] || summary.ranked[0];

  dom.activeCount.textContent = String(summary.activeCount);
  dom.activeLimit.textContent = `上限 ${state.settings.maxActive}件`;
  dom.holdCount.textContent = String(summary.holdCount);
  dom.staleCount.textContent = String(summary.staleCount);
  dom.staleLabel.textContent = `${state.settings.staleDays}日以上未更新`;
  dom.focusCounter.textContent = `${focusItems.length} / ${state.settings.focusLimit}`;

  if (top) {
    dom.topTitle.textContent = top.item.title;
    dom.topAction.textContent = top.result.readiness.ready
      ? top.item.nextAction
      : `実行前に整理が必要：${top.result.readiness.label}`;
  } else {
    dom.topTitle.textContent = 'まだありません';
    dom.topAction.textContent = '項目を追加すると順位を計算します。';
  }

  renderAlerts(summary, focusItems);
  renderFocusList(focusItems);
  renderDomainLoad(summary.domainCounts);
  renderGateList(summary.ranked.filter(({ result }) => !result.readiness.ready));
}

function renderAlerts(summary, focusItems) {
  const alerts = [];
  if (summary.overloaded) {
    alerts.push({
      type: 'danger-alert',
      text: `進行中が上限${state.settings.maxActive}件を超えています。新規追加より、完了か保留箱への移動を優先してください。`,
    });
  }
  if (summary.staleCount > 0) {
    alerts.push({
      type: '',
      text: `${summary.staleCount}件が${state.settings.staleDays}日以上更新されていません。次の一手を具体化するか、保留箱へ移してください。`,
    });
  }
  if (summary.activeCount > 0 && focusItems.length === 0) {
    alerts.push({
      type: 'danger-alert',
      text: '実行可能な項目がありません。根拠・撤退条件・次の一手を補ってください。',
    });
  }
  dom.alertArea.replaceChildren(...alerts.map(({ type, text }) => {
    const element = document.createElement('div');
    element.className = `alert ${type}`.trim();
    element.textContent = text;
    return element;
  }));
}

function renderFocusList(focusItems) {
  if (!focusItems.length) {
    dom.focusList.className = 'focus-list empty-state';
    dom.focusList.innerHTML = '<p>実行可能な項目がありません。「追加」または「全件」から整理してください。</p>';
    return;
  }
  dom.focusList.className = 'focus-list';
  dom.focusList.replaceChildren(...focusItems.map(({ item, result }, index) => {
    const node = dom.focusItemTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id;
    $('[data-rank]', node).textContent = String(index + 1);
    $('[data-domain]', node).textContent = DOMAINS[item.domain];
    setReadiness($('[data-readiness]', node), result.readiness);
    setDeadline($('[data-deadline]', node), item.deadline);
    $('[data-title]', node).textContent = item.title;
    $('[data-action]', node).textContent = item.nextAction;
    $('[data-explanation]', node).textContent = result.explanation;
    $('[data-score]', node).textContent = String(result.score);
    return node;
  }));
}

function renderDomainLoad(domainCounts) {
  const maximum = Math.max(1, ...Object.values(domainCounts));
  const rows = Object.entries(DOMAINS)
    .filter(([key]) => domainCounts[key] > 0)
    .map(([key, label]) => {
      const row = document.createElement('div');
      row.className = 'domain-row';
      const name = document.createElement('span');
      name.textContent = label;
      const track = document.createElement('div');
      track.className = 'load-track';
      const fill = document.createElement('div');
      fill.className = 'load-fill';
      fill.style.width = `${Math.round((domainCounts[key] / maximum) * 100)}%`;
      track.append(fill);
      const count = document.createElement('strong');
      count.textContent = String(domainCounts[key]);
      row.append(name, track, count);
      return row;
    });

  if (!rows.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = '<p>進行中の項目はありません。</p>';
    dom.domainLoad.replaceChildren(empty);
  } else {
    dom.domainLoad.replaceChildren(...rows);
  }
}

function renderGateList(holds) {
  if (!holds.length) {
    dom.gateList.className = 'gate-list empty-state';
    dom.gateList.innerHTML = '<p>保留中の判断はありません。</p>';
    return;
  }
  dom.gateList.className = 'gate-list';
  dom.gateList.replaceChildren(...holds.slice(0, 6).map(({ item, result }) => {
    const element = document.createElement('article');
    element.className = 'gate-item';
    element.dataset.id = item.id;
    const title = document.createElement('strong');
    title.textContent = `${item.title} — ${result.readiness.label}`;
    const list = document.createElement('ul');
    result.readiness.warnings.forEach((warning) => {
      const li = document.createElement('li');
      li.textContent = warning;
      list.append(li);
    });
    const edit = document.createElement('button');
    edit.className = 'button small secondary';
    edit.type = 'button';
    edit.dataset.action = 'edit';
    edit.textContent = '整理する';
    edit.style.marginTop = '10px';
    element.append(title, list, edit);
    return element;
  }));
}

function renderQueue() {
  const search = dom.searchInput.value.trim().toLocaleLowerCase('ja-JP');
  const domain = dom.domainFilter.value;
  const status = dom.statusFilter.value;
  const statusOrder = { active: 0, waiting: 1, parked: 2, done: 3 };

  const rankedMap = new Map(rankItems(state.items, state.mode).map((entry) => [entry.item.id, entry]));
  const visible = state.items
    .filter((item) => domain === 'all' || item.domain === domain)
    .filter((item) => status === 'all' || item.status === status)
    .filter((item) => {
      if (!search) return true;
      return [item.title, item.nextAction, item.notes, item.thesis, item.invalidation]
        .join(' ')
        .toLocaleLowerCase('ja-JP')
        .includes(search);
    })
    .sort((a, b) => {
      if (statusOrder[a.status] !== statusOrder[b.status]) return statusOrder[a.status] - statusOrder[b.status];
      const aScore = rankedMap.get(a.id)?.result.score ?? scoreItem(a, state.mode).score;
      const bScore = rankedMap.get(b.id)?.result.score ?? scoreItem(b, state.mode).score;
      return bScore - aScore || b.updatedAt.localeCompare(a.updatedAt);
    });

  if (!visible.length) {
    dom.queueList.className = 'queue-list empty-state';
    dom.queueList.innerHTML = '<p>条件に合う項目はありません。</p>';
    return;
  }

  dom.queueList.className = 'queue-list';
  dom.queueList.replaceChildren(...visible.map((item) => {
    const result = scoreItem(item, state.mode);
    const node = dom.queueItemTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id;
    node.classList.toggle('is-done', item.status === 'done');
    $('[data-domain]', node).textContent = DOMAINS[item.domain];
    $('[data-status]', node).textContent = STATUSES[item.status];
    setReadiness($('[data-readiness]', node), result.readiness);
    setDeadline($('[data-deadline]', node), item.deadline);
    $('[data-title]', node).textContent = item.title;
    $('[data-next-action]', node).textContent = item.nextAction || '次の一手が未設定です。';
    const notes = $('[data-notes]', node);
    notes.textContent = item.notes;
    notes.hidden = !item.notes;
    $('[data-score]', node).textContent = item.status === 'active' ? String(result.score) : '—';
    $('[data-explanation]', node).textContent = item.status === 'active' ? result.explanation : '順位対象外';
    const warning = $('[data-warning]', node);
    if (result.readiness.warnings.length) {
      warning.hidden = false;
      warning.textContent = result.readiness.warnings.join(' / ');
    }
    const doneButton = $('[data-action="toggle-done"]', node);
    doneButton.textContent = item.status === 'done' ? '再開' : '完了';
    const parkButton = $('[data-action="park"]', node);
    parkButton.textContent = item.status === 'parked' ? '戻す' : '保留箱';
    return node;
  }));
}

function renderReview() {
  const summary = summarizeState(state);
  dom.contextOutput.value = buildConsultationContext(state);
  dom.focusLimitInput.value = String(state.settings.focusLimit);
  dom.maxActiveInput.value = String(state.settings.maxActive);
  dom.staleDaysInput.value = String(state.settings.staleDays);

  if (!summary.completedThisWeek.length) {
    dom.completedList.className = 'compact-list empty-state';
    dom.completedList.innerHTML = '<p>直近7日の完了はありません。</p>';
    return;
  }

  dom.completedList.className = 'compact-list';
  dom.completedList.replaceChildren(...summary.completedThisWeek
    .sort((a, b) => (b.completedAt || b.updatedAt).localeCompare(a.completedAt || a.updatedAt))
    .map((item) => {
      const row = document.createElement('div');
      row.className = 'compact-item';
      const text = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = item.title;
      const meta = document.createElement('small');
      meta.textContent = DOMAINS[item.domain];
      text.append(title, meta);
      const date = document.createElement('small');
      date.textContent = formatDate(item.completedAt || item.updatedAt);
      row.append(text, date);
      return row;
    }));
}

function setReadiness(element, readiness) {
  element.textContent = readiness.label;
  element.dataset.state = readiness.state;
}

function setDeadline(element, dateText) {
  element.classList.remove('is-urgent', 'is-overdue');
  const days = daysUntil(dateText);
  if (days === null) {
    element.textContent = '期限なし';
    return;
  }
  if (days < 0) {
    element.textContent = `${Math.abs(days)}日超過`;
    element.classList.add('is-overdue');
    return;
  }
  if (days === 0) {
    element.textContent = '今日';
    element.classList.add('is-urgent');
    return;
  }
  element.textContent = `あと${days}日`;
  if (days <= 3) element.classList.add('is-urgent');
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ja-JP', { month: 'numeric', day: 'numeric' }).format(date);
}

function saveSettings() {
  const next = {
    focusLimit: Number(dom.focusLimitInput.value),
    maxActive: Number(dom.maxActiveInput.value),
    staleDays: Number(dom.staleDaysInput.value),
  };
  commitState({ ...state, settings: next }, '上限を保存しました。');
}

async function copyContext() {
  const text = buildConsultationContext(state);
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    dom.contextOutput.focus();
    dom.contextOutput.select();
    document.execCommand('copy');
    window.getSelection()?.removeAllRanges();
  }
  showToast('相談用コンテキストをコピーしました。');
}

function exportData() {
  const payload = JSON.stringify({ ...state, exportedAt: new Date().toISOString() }, null, 2);
  const blob = new Blob([payload], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `same-compass-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast('JSONを書き出しました。');
}

async function importData(file) {
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    const imported = normalizeState(parsed);
    if (!window.confirm(`現在のデータを、読み込んだ${imported.items.length}件で置き換えます。`)) return;
    commitState(imported, 'JSONを読み込みました。');
  } catch (error) {
    console.error(error);
    showToast('JSONを読み込めませんでした。形式を確認してください。', true);
  } finally {
    dom.importInput.value = '';
  }
}

function clearData() {
  if (!window.confirm('すべての項目と設定を削除します。元に戻せません。')) return;
  commitState(createInitialState(), 'すべて削除しました。');
  resetForm();
}

function showToast(message, danger = false) {
  window.clearTimeout(toastTimer);
  dom.toast.textContent = message;
  dom.toast.style.background = danger ? 'var(--danger)' : 'var(--accent)';
  dom.toast.hidden = false;
  toastTimer = window.setTimeout(() => { dom.toast.hidden = true; }, 3200);
}

function bindEvents() {
  dom.tabs.forEach((button) => button.addEventListener('click', () => switchTab(button.dataset.tab)));

  dom.templateButtons.forEach((button) => button.addEventListener('click', () => applyTemplate(button.dataset.template)));

  dom.modeSelect.addEventListener('change', () => {
    commitState({ ...state, mode: dom.modeSelect.value }, `モードを「${MODES[dom.modeSelect.value].label}」に変更しました。`);
  });

  [dom.quickAddButton, dom.queueAddButton].forEach((button) => button.addEventListener('click', () => {
    resetForm();
    switchTab('editor');
    dom.titleInput.focus();
  }));

  dom.itemForm.addEventListener('submit', handleFormSubmit);
  dom.resetFormButton.addEventListener('click', resetForm);
  dom.cancelEditButton.addEventListener('click', () => {
    resetForm();
    switchTab('queue');
  });

  dom.highStakesInput.addEventListener('change', updateLiveScore);
  dom.itemForm.addEventListener('input', updateLiveScore);
  dom.itemForm.addEventListener('change', updateLiveScore);

  [dom.searchInput, dom.domainFilter, dom.statusFilter].forEach((input) => {
    input.addEventListener(input === dom.searchInput ? 'input' : 'change', renderQueue);
  });

  dom.focusList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    const item = event.target.closest('[data-id]');
    if (button && item) handleItemAction(button.dataset.action, item.dataset.id);
  });

  dom.queueList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    const item = event.target.closest('[data-id]');
    if (button && item) handleItemAction(button.dataset.action, item.dataset.id);
  });

  dom.gateList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    const item = event.target.closest('[data-id]');
    if (button && item) handleItemAction(button.dataset.action, item.dataset.id);
  });

  dom.copyContextButton.addEventListener('click', copyContext);
  dom.saveSettingsButton.addEventListener('click', saveSettings);
  dom.exportButton.addEventListener('click', exportData);
  dom.importInput.addEventListener('change', () => importData(dom.importInput.files?.[0]));
  dom.clearButton.addEventListener('click', clearData);

  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try {
      state = normalizeState(JSON.parse(event.newValue));
      renderAll();
      showToast('別タブの変更を反映しました。');
    } catch (error) {
      console.warn('Cross-tab state could not be read.', error);
    }
  });
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || !/^https?:$/.test(location.protocol)) return;
  try {
    await navigator.serviceWorker.register('./sw.js');
  } catch (error) {
    console.warn('Service worker registration failed.', error);
  }
}

initializeSelects();
bindEvents();
resetForm();
renderAll();
registerServiceWorker();
