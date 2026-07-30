#!/usr/bin/env python3
"""Select funded GitHub issues that still appear unassigned and without submitted PRs."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path("market-output/trusted-bounties.json")
OUTPUT = Path("market-output/issuehunt-uncontested.json")
EXCLUDED_OWNERS = {"sindresorhus"}
BLOCKED = (
    "accessibility api",
    "macos",
    "ios is priority",
    "hardware",
    "security exploit",
    "remote code execution",
    "adult",
    "porn",
    "defence",
    "bypass",
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def submitted_pr_count(body: str) -> int:
    marker = "### Submitted pull Requests"
    if marker not in body:
        return 0
    section = body.split(marker, 1)[1].split("---", 1)[0]
    return len(re.findall(r"^- \[#?\d|^- \[", section, flags=re.MULTILINE))


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    source = data.get("actionable", []) if isinstance(data, Mapping) else []
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in source:
        if not isinstance(item, Mapping):
            continue
        repo = str(item.get("repo") or "")
        owner = repo.split("/", 1)[0].lower() if "/" in repo else ""
        body = str(item.get("body_excerpt") or "")
        text = f"{repo}\n{item.get('title', '')}\n{body}".lower()
        pr_count = submitted_pr_count(body)
        blockers = []
        if owner in EXCLUDED_OWNERS:
            blockers.append("owner interaction restrictions observed")
        if item.get("assignees"):
            blockers.append("assigned")
        if item.get("open_competing_prs"):
            blockers.append("open competing PR")
        if item.get("safety_flags"):
            blockers.extend(str(v) for v in item.get("safety_flags") or [])
        if pr_count:
            blockers.append(f"IssueHunt section lists {pr_count} submitted PR(s)")
        if any(marker in text for marker in BLOCKED):
            blockers.append("environment, scope, or safety blocker")
        reward = float(item.get("reward_usd") or 0)
        if not (1 <= reward <= 500):
            blockers.append("reward outside bounded range")
        compact = {
            "repo": repo,
            "issue_number": item.get("issue_number"),
            "title": item.get("title"),
            "url": item.get("url"),
            "reward_usd": reward,
            "language": item.get("repo_language"),
            "repo_stars": item.get("repo_stars"),
            "updated_at": item.get("updated_at"),
            "selector_score": item.get("selector_score"),
            "submitted_pr_count": pr_count,
            "blockers": list(dict.fromkeys(blockers)),
            "scope_excerpt": body[:2500],
        }
        if blockers:
            excluded.append(compact)
        else:
            selected.append(compact)
    selected.sort(key=lambda x: (float(x.get("selector_score") or 0), x["reward_usd"]), reverse=True)
    excluded.sort(key=lambda x: (len(x["blockers"]), -x["reward_usd"]))
    report = {
        "generated_at": now(),
        "selected_count": len(selected),
        "selected": selected,
        "excluded_count": len(excluded),
        "closest_excluded": excluded[:30],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "selected_count": len(selected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
