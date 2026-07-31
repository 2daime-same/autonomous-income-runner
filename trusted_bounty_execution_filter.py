#!/usr/bin/env python3
"""Second-stage execution filter for trusted funded GitHub bounties.

The trusted radar proves that a known bounty platform is attached. This filter
removes stale, rewarded, already-submitted, paused, or clearly oversized tasks
before implementation effort is committed. It is read-only.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import github_bounty_radar as github

INPUT = Path("market-output/trusted-bounties.json")
OUTPUT = Path("market-output/trusted-bounties-executable.json")

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
HOLD_PATTERNS = (
    r"\bhold off\b",
    r"\bplease wait\b",
    r"\bdo not (?:start|work|submit|attempt)\b",
    r"\bdon't (?:start|work|submit|attempt)\b",
    r"\bnot accepting (?:new )?(?:attempts|submissions|prs|pull requests)\b",
    r"\bno (?:new )?(?:attempts|submissions|prs|pull requests)\b",
    r"\bnot ready for (?:implementation|development)\b",
    r"\btemporarily closed to contributions\b",
)
LARGE_SCOPE = (
    "accessibility api",
    "complete rewrite",
    "full rewrite",
    "across desktop and mobile",
    "all platforms",
    "operating system",
    "architecture upgrade",
    "parallel processing",
    "map partition",
    "new framework",
    "entire application",
)
SMALL_SCOPE = (
    "typo", "readme", "documentation", "validation", "error message", "unit test",
    "regression test", "null", "edge case", "cli", "flag", "fallback", "duplicate",
    "performance", "cache", "timeout", "regex", "format", "parser", "serialization",
)
COMPETITOR_URL = re.compile(r"https://github\.com/[^\s)]+/pull/\d+", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def explicit_submissions(body: str) -> list[str]:
    matches: list[str] = []
    section = re.search(r"Submitted pull Requests(?P<body>.*?)(?:\n---|</details>|$)", body, re.I | re.S)
    if section:
        matches.extend(COMPETITOR_URL.findall(section.group("body")))
        matches.extend(re.findall(r"- \[#?\d+[^\n]*\]", section.group("body")))
    return sorted(set(matches))


def inspect_comments(repo: str, number: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    holdoffs: list[dict[str, Any]] = []
    competitors: list[dict[str, Any]] = []
    for comment in github.fetch_comments(repo, number):
        if not isinstance(comment, Mapping):
            continue
        body = str(comment.get("body") or "")
        association = str(comment.get("author_association") or "").upper()
        user = comment.get("user") if isinstance(comment.get("user"), Mapping) else {}
        login = str(user.get("login") or "")
        if association in MAINTAINER_ASSOCIATIONS:
            matched = [pattern for pattern in HOLD_PATTERNS if re.search(pattern, body, re.I)]
            if matched:
                holdoffs.append({
                    "login": login,
                    "association": association,
                    "url": comment.get("html_url"),
                    "excerpt": re.sub(r"\s+", " ", body).strip()[:700],
                    "matched_rules": matched,
                })
        urls = COMPETITOR_URL.findall(body)
        if urls and login.lower() not in {"issuehuntbot", "opire-bot", "algora-pbc[bot]"}:
            competitors.append({
                "login": login,
                "association": association,
                "url": comment.get("html_url"),
                "pull_requests": sorted(set(urls)),
                "excerpt": re.sub(r"\s+", " ", body).strip()[:700],
            })
    return holdoffs, competitors


def scope_score(item: Mapping[str, Any]) -> tuple[float, list[str]]:
    body = str(item.get("body_excerpt") or "").lower()
    title = str(item.get("title") or "").lower()
    text = title + "\n" + body
    score = float(item.get("selector_score") or 0.0)
    reasons: list[str] = []
    if any(marker in text for marker in SMALL_SCOPE):
        score += 20
        reasons.append("small/testable scope marker")
    if any(marker in text for marker in LARGE_SCOPE):
        score -= 45
        reasons.append("large or cross-platform scope")
    language = str(item.get("repo_language") or "").lower()
    if language in {"python", "javascript", "typescript", "html", "shell"}:
        score += 10
    if language in {"c++", "objective-c", "swift", "dm"}:
        score -= 15
    reward = float(item.get("reward_usd") or 0.0)
    if 1 <= reward <= 100:
        score += 8
        reasons.append("first-income-sized reward")
    if reward > 500:
        score -= 15
    return round(score, 2), reasons


def main() -> int:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    items = payload.get("actionable") if isinstance(payload, Mapping) else []
    if not isinstance(items, list):
        raise RuntimeError("trusted bounty report has no actionable array")

    executable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        repo = str(item.get("repo") or "")
        number = item.get("issue_number")
        body = str(item.get("body_excerpt") or "")
        reasons: list[str] = []

        submissions = explicit_submissions(body)
        if submissions:
            reasons.append("IssueHunt body already lists submitted pull requests")
        if re.search(r"has been rewarded|Rewarded-%23|\brewarded\b", body, re.I):
            reasons.append("issue body indicates a reward has already been issued")

        holdoffs: list[dict[str, Any]] = []
        competitors: list[dict[str, Any]] = []
        if repo and isinstance(number, int):
            try:
                holdoffs, competitors = inspect_comments(repo, number)
            except Exception as exc:
                reasons.append(f"comment validation failed: {type(exc).__name__}")
        else:
            reasons.append("missing repository or issue number")
        if holdoffs:
            reasons.append("maintainer requested hold-off")
        if competitors:
            reasons.append("a contributor reported an active or submitted pull request")

        score, score_reasons = scope_score(item)
        compact = {
            "execution_score": score,
            "execution_score_reasons": score_reasons,
            "repo": repo,
            "issue_number": number,
            "title": item.get("title"),
            "url": item.get("url"),
            "reward_usd": item.get("reward_usd"),
            "repo_language": item.get("repo_language"),
            "repo_stars": item.get("repo_stars"),
            "updated_at": item.get("updated_at"),
            "body_excerpt": body[:3500],
            "maintainer_holdoffs": holdoffs,
            "competitor_signals": competitors,
            "body_submitted_pr_signals": submissions,
        }
        if reasons:
            compact["exclusions"] = sorted(set(reasons))
            excluded.append(compact)
        else:
            executable.append(compact)

    executable.sort(key=lambda item: float(item.get("execution_score") or -999), reverse=True)
    excluded.sort(key=lambda item: float(item.get("execution_score") or -999), reverse=True)
    result = {
        "generated_at": now_iso(),
        "source": str(INPUT),
        "input_count": len(items),
        "executable_count": len(executable),
        "executable": executable,
        "excluded_count": len(excluded),
        "excluded": excluded,
        "writes_performed": [],
        "expenses_usd": 0,
    }
    atomic_json(OUTPUT, result)
    print(json.dumps({"ok": True, "executable": len(executable), "excluded": len(excluded)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
