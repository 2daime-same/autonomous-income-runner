#!/usr/bin/env python3
"""Fail-safe post-filter for BountyHub candidates.

The upstream selector can miss work happening in a sibling implementation
repository or in issue comments that link a PR without using a canonical
"fixes #N" reference.  This pass re-reads comments only for candidates that
would otherwise be called actionable and removes large full-stack scopes or
current human implementation signals.

Read-only network behavior: GitHub GET requests only.  It never claims,
comments, submits, pays, signs, or authenticates to BountyHub.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import github_bounty_radar as github

INPUT = Path(os.environ.get("BOUNTYHUB_OUTPUT", "market-output/bountyhub-candidates.json"))

BOT_LOGINS = {"bountyhub-bot", "github-actions[bot]", "dependabot[bot]"}
LARGE_SCOPE_MARKERS = (
    "implemented across desktop and mobile",
    "implement across desktop and mobile",
    "fullstack",
    "full-stack",
    "backend + gateway + frontend",
    "complete rewrite",
    "entire application",
)
ATTEMPT_MARKERS = (
    "/claim",
    "i can take this on",
    "i'll work on",
    "i will work on",
    "work on implementing",
    "claim and tackle",
    "submitted a mobile",
    "submitted a full",
    "submitted a design",
    "opened a focused",
    "opened pr",
    "full-stack pr",
    "already accepted mobile",
    "already doing on the backend",
    "github.com/fluxerapp/fluxer/pull/",
)
VACATE_MARKERS = (
    "vacating my claim",
    "withdraw my claim",
    "withdrawing my claim",
    "no longer working on",
    "will not be working on",
)


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def current_attempt_signals(comments: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Return the latest non-vacated implementation signal per GitHub user."""
    active: dict[str, dict[str, str]] = {}
    for comment in comments:
        user_value = comment.get("user")
        user = user_value if isinstance(user_value, Mapping) else {}
        login = str(user.get("login") or "").strip()
        if not login or login.lower() in BOT_LOGINS or login.lower().endswith("[bot]"):
            continue
        body = str(comment.get("body") or "")
        lower = body.lower()
        if any(marker in lower for marker in VACATE_MARKERS):
            active.pop(login.lower(), None)
            continue
        if any(marker in lower for marker in ATTEMPT_MARKERS):
            active[login.lower()] = {
                "login": login,
                "excerpt": " ".join(body.split())[:600],
            }
    return sorted(active.values(), key=lambda value: value["login"].lower())


def postfilter(data: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(data)
    actionable_value = data.get("actionable")
    actionable = [dict(item) for item in actionable_value if isinstance(item, Mapping)] if isinstance(actionable_value, list) else []
    inspected_value = data.get("inspected")
    inspected = [dict(item) for item in inspected_value if isinstance(item, Mapping)] if isinstance(inspected_value, list) else []

    kept: list[dict[str, Any]] = []
    exclusions_applied: list[dict[str, Any]] = []
    for item in actionable:
        reasons = [str(reason) for reason in item.get("exclusions", []) if str(reason)]
        combined_text = "\n".join(
            [
                str(item.get("title") or ""),
                str(item.get("scope_excerpt") or ""),
                str(item.get("additional_description") or ""),
            ]
        ).lower()
        if any(marker in combined_text for marker in LARGE_SCOPE_MARKERS):
            reasons.append("large full-stack or cross-platform scope is unsuitable for first-income execution")

        repo = str(item.get("repository") or "").strip()
        try:
            issue_number = int(item.get("issue_number"))
        except (TypeError, ValueError):
            issue_number = 0
        live_signals: list[dict[str, str]] = []
        if repo and issue_number > 0:
            try:
                live_signals = current_attempt_signals(github.fetch_comments(repo, issue_number))
            except Exception as exc:  # fail closed when validation is unavailable
                reasons.append(f"live comment competition validation failed: {type(exc).__name__}")
        else:
            reasons.append("missing GitHub locator during live competition validation")

        if live_signals:
            reasons.append("current competing implementation signal exists in issue comments")
            item["live_comment_competition"] = live_signals

        item["exclusions"] = sorted(set(reasons))
        if item["exclusions"]:
            exclusions_applied.append(
                {
                    "repository": repo,
                    "issue_number": issue_number,
                    "title": item.get("title"),
                    "reasons": item["exclusions"],
                    "live_comment_competition": live_signals,
                }
            )
            replaced = False
            for index, inspected_item in enumerate(inspected):
                if (
                    inspected_item.get("repository") == item.get("repository")
                    and inspected_item.get("issue_number") == item.get("issue_number")
                ):
                    inspected[index] = item
                    replaced = True
                    break
            if not replaced:
                inspected.append(item)
        else:
            kept.append(item)

    output["actionable"] = kept
    output["actionable_count"] = len(kept)
    output["inspected"] = inspected
    output["postfilter"] = {
        "policy": "exclude large first-income scopes and live non-vacated implementation signals from issue comments",
        "checked_count": len(actionable),
        "excluded_count": len(exclusions_applied),
        "exclusions_applied": exclusions_applied,
    }
    return output


def main() -> int:
    if not INPUT.exists():
        raise SystemExit(f"missing selector output: {INPUT}")
    value = json.loads(INPUT.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise SystemExit("selector output must be a JSON object")
    filtered = postfilter(value)
    atomic_write(INPUT, filtered)
    print(
        json.dumps(
            {
                "checked": filtered["postfilter"]["checked_count"],
                "excluded": filtered["postfilter"]["excluded_count"],
                "actionable": filtered["actionable_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
