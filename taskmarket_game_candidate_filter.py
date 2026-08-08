#!/usr/bin/env python3
"""Extract current Taskmarket browser-game bounties from the live shortlist."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path("taskmarket-output/live-open-shortlist.json")
OUTPUT = Path("taskmarket-output/current-game-candidates.json")

value = json.loads(SOURCE.read_text(encoding="utf-8"))
rows = value.get("candidates") if isinstance(value, Mapping) else []
selected: list[dict[str, Any]] = []
keywords = (
    "game", "three.js", "threejs", "arcade", "runner", "stack", "catch", "patrol",
    "traffic", "browser", "score", "high score", "playable",
)
for row in rows or []:
    if not isinstance(row, Mapping):
        continue
    text = f"{row.get('title', '')} {row.get('description', '')}".lower()
    tags = [str(tag).lower() for tag in row.get("tags") or []]
    if str(row.get("mode") or "").lower() != "bounty":
        continue
    if float(row.get("reward_usdc") or 0) < 9:
        continue
    if not any(keyword in text for keyword in keywords) and not any(tag in {"threejs", "game", "browser-game", "game-development"} for tag in tags):
        continue
    if row.get("worker_payment_action_count") not in (0, None):
        continue
    selected.append({
        "task_id": row.get("task_id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "reward_usdc": row.get("reward_usdc"),
        "net_reward_usdc": row.get("net_reward_usdc"),
        "submission_count": row.get("submission_count"),
        "hours_left": row.get("hours_left"),
        "warnings": row.get("warnings") or [],
        "tags": row.get("tags") or [],
        "task_url": row.get("task_url"),
    })
selected.sort(key=lambda row: (int(row.get("submission_count") or 0), -float(row.get("net_reward_usdc") or 0)))
OUTPUT.write_text(json.dumps({
    "generated_at": value.get("generated_at") if isinstance(value, Mapping) else None,
    "candidate_count": len(selected),
    "candidates": selected,
    "expenses_usdc": 0,
    "verified_income_usdc": 0,
}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"ok": True, "candidates": len(selected)}))
