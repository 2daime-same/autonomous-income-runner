#!/usr/bin/env python3
"""Compact the GitHub-native bounty radar into reviewable direct candidates."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path(os.environ.get("GITHUB_RADAR_FILE", "market-output/github-bounties.json"))
OUTPUT = Path(os.environ.get("GITHUB_COMPACT_FILE", "market-output/github-bounties-compact.json"))
EXCLUDED_OWNERS = {"sindresorhus"}
BLOCKED_TEXT = (
    "bountyscout",
    "bounty alert",
    "active bounty scan",
    "marketing",
    "social media",
    "adult",
    "porn",
    "genital",
    "pregnancy",
    "security exploit",
    "remote code execution",
    "idor",
    "ssrf",
    "xxe",
    "jwt",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidates = data.get("recommended") if isinstance(data, Mapping) else None
    if not isinstance(candidates, list):
        candidates = data.get("ranked_candidates", []) if isinstance(data, Mapping) else []

    selected = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        repo = str(item.get("repo") or "")
        owner = repo.split("/", 1)[0].lower() if "/" in repo else ""
        title = str(item.get("title") or "")
        body = str(item.get("body_excerpt") or "")
        value = f"{repo}\n{title}\n{body}".lower()
        evidence = item.get("reward_evidence") if isinstance(item.get("reward_evidence"), Mapping) else {}
        reward = float(evidence.get("max_amount_usd") or 0)
        direct = bool(evidence.get("direct_reward_evidence"))
        if owner in EXCLUDED_OWNERS:
            continue
        if any(marker in value for marker in BLOCKED_TEXT):
            continue
        if not direct or not (1 <= reward <= 1000):
            continue
        if item.get("assignees") or item.get("open_competing_prs") or evidence.get("attempt_count"):
            continue
        selected.append(
            {
                "score": item.get("score"),
                "repo": repo,
                "issue_number": item.get("issue_number"),
                "title": title,
                "url": item.get("url"),
                "reward_usd": reward,
                "language": item.get("repo_language"),
                "repo_stars": item.get("repo_stars"),
                "updated_at": item.get("updated_at"),
                "direct_comments": evidence.get("direct_comments"),
                "markers": evidence.get("markers"),
                "scope_excerpt": body[:1200],
            }
        )

    selected.sort(key=lambda item: (float(item.get("score") or 0), -float(item["reward_usd"])), reverse=True)
    result = {
        "generated_at": now_iso(),
        "source_generated_at": data.get("generated_at") if isinstance(data, Mapping) else None,
        "selected_count": len(selected),
        "selected": selected[:30],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "selected_count": len(selected), "top": selected[:3]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
