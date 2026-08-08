#!/usr/bin/env python3
"""Extract compact, non-film Taskmarket browser-game bounties."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

source = json.loads(Path('taskmarket-output/live-open-shortlist.json').read_text(encoding='utf-8'))
rows = source.get('candidates') if isinstance(source, Mapping) else []
selected = []
for row in rows or []:
    if not isinstance(row, Mapping):
        continue
    text = f"{row.get('title', '')} {row.get('description', '')}".lower()
    tags = {str(tag).lower() for tag in row.get('tags') or []}
    if str(row.get('mode') or '').lower() != 'bounty':
        continue
    if float(row.get('reward_usdc') or 0) < 9:
        continue
    if tags & {'1980s', 'visual-storytelling', 'animation', 'task-drop', 'tv'}:
        continue
    if not any(term in text for term in ('required gameplay', 'browser game', 'arcade game', 'high score', 'game using three.js', 'playable')):
        continue
    selected.append({
        'task_id': row.get('task_id'),
        'title': row.get('title'),
        'reward_usdc': row.get('reward_usdc'),
        'net_reward_usdc': row.get('net_reward_usdc'),
        'submission_count': row.get('submission_count'),
        'hours_left': row.get('hours_left'),
        'tags': list(row.get('tags') or []),
        'description_excerpt': str(row.get('description') or '')[:1800],
        'task_url': row.get('task_url'),
    })
selected.sort(key=lambda row: (int(row.get('submission_count') or 0), -float(row.get('net_reward_usdc') or 0)))
Path('taskmarket-output/current-playable-candidates.json').write_text(json.dumps({
    'generated_at': source.get('generated_at') if isinstance(source, Mapping) else None,
    'candidate_count': len(selected),
    'candidates': selected,
    'expenses_usdc': 0,
    'verified_income_usdc': 0,
}, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps({'ok': True, 'candidates': len(selected)}))
