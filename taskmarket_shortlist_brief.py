#!/usr/bin/env python3
"""Create a compact review view from the current read-only Taskmarket shortlist."""
from __future__ import annotations

import json
from pathlib import Path

SOURCE = Path("taskmarket-output/live-open-shortlist.json")
OUTPUT = Path("taskmarket-output/live-open-brief.json")

value = json.loads(SOURCE.read_text(encoding="utf-8"))
rows = value.get("candidates") if isinstance(value, dict) else []
brief = []
for row in rows or []:
    if not isinstance(row, dict):
        continue
    brief.append({
        "task_id": row.get("task_id"),
        "title": row.get("title"),
        "mode": row.get("mode"),
        "reward_usdc": row.get("reward_usdc"),
        "net_reward_usdc": row.get("net_reward_usdc"),
        "submission_count": row.get("submission_count"),
        "pitch_count": row.get("pitch_count"),
        "hours_left": row.get("hours_left"),
        "warnings": row.get("warnings") or [],
        "worker_payment_action_count": row.get("worker_payment_action_count"),
        "tags": row.get("tags") or [],
        "description_excerpt": str(row.get("description") or "")[:700],
    })
OUTPUT.write_text(json.dumps({
    "generated_at": value.get("generated_at") if isinstance(value, dict) else None,
    "candidate_count": len(brief),
    "candidates": brief,
    "expenses_usdc": 0,
    "verified_income_usdc": 0,
}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"ok": True, "candidates": len(brief)}))
