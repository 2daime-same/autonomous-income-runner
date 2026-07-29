#!/usr/bin/env python3
"""Reduce the trusted-bounty evidence into small, low-friction fallback tasks."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path(os.environ.get("TRUSTED_BOUNTIES_FILE", "market-output/trusted-bounties.json"))
OUTPUT = Path(os.environ.get("COMPACT_SHORTLIST_FILE", "market-output/compact-bounty-shortlist.json"))
SUPPORTED = {"javascript", "typescript", "python", "go", "html", "shell"}
BLOCKED = (
    "ios",
    "android",
    "macos",
    "mojave",
    "physical device",
    "video of it working",
    "record a video",
    "accessibility api",
    "desktop and mobile",
    "across desktop and mobile",
    "complete rewrite",
    "full rewrite",
    "entire application",
    "security audit",
    "penetration test",
    "exploit",
    "adult",
    "genital",
    "porn",
    "marketing",
    "social media",
)
SMALL = (
    "typo",
    "documentation",
    "readme",
    "unit test",
    "test harness",
    "error message",
    "null check",
    "regex",
    "fallback",
    "pagination",
    "validation",
    "duplicate",
    "edge case",
    "performance",
    "processing time",
    "cli flag",
    "serialization",
    "deserialization",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text(item: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            str(item.get("title") or ""),
            str(item.get("body_excerpt") or ""),
            str(item.get("repo") or ""),
        ]
    ).lower()


def rank(item: Mapping[str, Any]) -> tuple[float, list[str]]:
    value = text(item)
    reward = float(item.get("reward_usd") or 0)
    language = str(item.get("repo_language") or "").lower()
    score = 0.0
    reasons: list[str] = []
    if 1 <= reward <= 25:
        score += 35
        reasons.append("first-payment-sized reward")
    elif reward <= 100:
        score += 22
    elif reward <= 250:
        score += 10
    else:
        score -= 25
    if language in SUPPORTED:
        score += 20
        reasons.append(f"supported language: {language}")
    if any(marker in value for marker in SMALL):
        score += 25
        reasons.append("small/testable scope marker")
    body_length = len(str(item.get("body_excerpt") or ""))
    if body_length <= 1200:
        score += 12
        reasons.append("compact specification")
    elif body_length > 5000:
        score -= 18
    stars = int(item.get("repo_stars") or 0)
    if stars >= 20:
        score += 8
    if item.get("direct_reward_evidence"):
        score += 15
        reasons.append("direct reward evidence")
    if item.get("attempt_count"):
        score -= 30
    if item.get("assignees"):
        score -= 30
    if item.get("open_competing_prs"):
        score -= 45
    if item.get("safety_flags"):
        score -= 50
    return score, reasons


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidates = data.get("actionable") if isinstance(data, dict) else None
    if not isinstance(candidates, list):
        raise RuntimeError("trusted-bounties.json has no actionable array")

    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        value = text(raw)
        blockers = [marker for marker in BLOCKED if marker in value]
        score, reasons = rank(raw)
        compact = {
            "score": round(score, 2),
            "title": raw.get("title"),
            "repo": raw.get("repo"),
            "issue_number": raw.get("issue_number"),
            "url": raw.get("url"),
            "reward_usd": raw.get("reward_usd"),
            "language": raw.get("repo_language"),
            "repo_stars": raw.get("repo_stars"),
            "attempt_count": raw.get("attempt_count"),
            "assignees": raw.get("assignees"),
            "open_competing_pr_count": len(raw.get("open_competing_prs") or []),
            "trust_programs": raw.get("trust_programs"),
            "reasons": reasons,
            "blockers": blockers,
            "scope_excerpt": str(raw.get("body_excerpt") or "")[:900],
        }
        if blockers or raw.get("safety_flags") or raw.get("attempt_count") or raw.get("assignees") or raw.get("open_competing_prs"):
            excluded.append(compact)
        else:
            selected.append(compact)

    selected.sort(key=lambda item: float(item["score"]), reverse=True)
    excluded.sort(key=lambda item: float(item["score"]), reverse=True)
    result = {
        "generated_at": now_iso(),
        "source": str(SOURCE),
        "selected_count": len(selected),
        "selected": selected[:30],
        "excluded_top": excluded[:20],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "selected": len(selected), "top": selected[:3]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
