#!/usr/bin/env python3
"""Reject BountyHub candidates when maintainers have paused new attempts."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import github_bounty_radar as github

INPUT = Path("market-output/bountyhub-candidates.json")
OUTPUT = Path("market-output/bountyhub-strict-candidates.json")

HOLD_PATTERNS = (
    r"\bhold off\b",
    r"\bplease wait\b",
    r"\bwait (?:for|until|on)\b",
    r"\bdo not (?:start|work|submit|attempt)\b",
    r"\bdon't (?:start|work|submit|attempt)\b",
    r"\bnot accepting (?:new )?(?:attempts|submissions|prs|pull requests)\b",
    r"\bno (?:new )?(?:attempts|submissions|prs|pull requests)\b",
    r"\bpause(?:d)? (?:work|submissions|attempts|implementation)\b",
    r"\bnot ready for (?:implementation|development)\b",
    r"\btemporarily closed to contributions\b",
    r"\bplease refrain from\b",
)
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def holdoff_signals(comments: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for comment in comments:
        association = str(comment.get("author_association") or "").upper()
        if association not in TRUSTED_ASSOCIATIONS:
            continue
        body = str(comment.get("body") or "")
        matched = [pattern for pattern in HOLD_PATTERNS if re.search(pattern, body, re.I)]
        if not matched:
            continue
        user = comment.get("user") if isinstance(comment.get("user"), Mapping) else {}
        signals.append({
            "login": str(user.get("login") or ""),
            "author_association": association,
            "created_at": comment.get("created_at"),
            "html_url": comment.get("html_url"),
            "excerpt": re.sub(r"\s+", " ", body).strip()[:700],
            "matched_rules": matched,
        })
    return signals


def main() -> int:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    inspected = payload.get("inspected") if isinstance(payload, Mapping) else []
    if not isinstance(inspected, list):
        raise RuntimeError("Unexpected BountyHub candidate shape")

    strict: list[dict[str, Any]] = []
    for raw in inspected:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        exclusions = list(item.get("exclusions") or [])
        repo = str(item.get("repository") or "")
        number = item.get("issue_number")
        signals: list[dict[str, Any]] = []
        if repo and isinstance(number, int):
            try:
                signals = holdoff_signals(github.fetch_comments(repo, number))
            except Exception as exc:
                exclusions.append(f"maintainer hold-off validation failed: {type(exc).__name__}")
        else:
            exclusions.append("missing repository or issue number")
        if signals:
            exclusions.append("maintainer requested hold-off or is not accepting new attempts")
        item["maintainer_holdoff_signals"] = signals
        item["exclusions"] = sorted(set(exclusions))
        strict.append(item)

    strict.sort(key=lambda item: float(item.get("score") or -999), reverse=True)
    actionable = [item for item in strict if not item.get("exclusions")]
    output = {
        "generated_at": now_iso(),
        "source": str(INPUT),
        "safety": "read-only GitHub comment validation; no claim, comment, PR, payment, or external write",
        "actionable_count": len(actionable),
        "actionable": actionable,
        "inspected": strict,
    }
    atomic_json(OUTPUT, output)
    print(json.dumps({
        "ok": True,
        "actionable": len(actionable),
        "holdoff_rejections": sum(bool(item.get("maintainer_holdoff_signals")) for item in strict),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
