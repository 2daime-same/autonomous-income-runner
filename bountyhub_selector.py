#!/usr/bin/env python3
"""Select BountyHub tasks that are funded, open, unclaimed, and executable.

The script uses the unauthenticated BountyHub listing API and GitHub's read-only
REST API. It never logs in, claims a bounty, submits a PR, pays, or mutates an
external service. Public payment-session identifiers and personal data are not
copied into the output.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import github_bounty_radar as github

API_URL = "https://api.bountyhub.dev/api/bounties?limit=100"
OUTPUT = Path(os.environ.get("BOUNTYHUB_OUTPUT", "market-output/bountyhub-candidates.json"))
TIMEOUT = 45

ADULT_OR_SEXUAL = (
    "splurt",
    "vore",
    "lewd",
    "genital",
    "penis",
    "vagina",
    "semen",
    "cum ",
    "breasts",
    "panty",
    "fetish",
    "erp",
    "bad dragon",
)

PHYSICAL_OR_ACCOUNT_BOUND = (
    "android device",
    "phone number",
    "sms verification",
    "wearos",
    "wear os",
    "smartwatch",
    "roku device",
    "google cast",
    "rcs functionality",
    "locked bootloader",
    "scooter",
    "physical device",
    "record a video",
    "video of it working",
    "test on ios",
    "test on android",
    "app attestation",
)

HIGH_RISK_SECURITY = (
    "security audit",
    "penetration test",
    "exploit",
    "vulnerability",
    "bypass authentication",
    "credential",
    "malware",
)

LARGE_SCOPE = (
    "implement across desktop and mobile",
    "complete rewrite",
    "full rewrite",
    "entire application",
    "all maps",
    "all platforms",
    "new protocol",
    "full support",
    "framework needed",
    "build a mobile",
    "build a desktop",
)

SMALL_SCOPE = (
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
    "one-line",
    "one line",
    "cli flag",
    "serialization",
    "deserialization",
)

ATTEMPT_MARKERS = (
    "/attempt",
    "/try",
    "i am working on this",
    "i'm working on this",
    "working on this issue",
    "submitted a fix",
    "opened pr",
    "pull request #",
)


def get_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "autonomous-income-runner-bountyhub-selector/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def unwrap_bounties(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, Mapping):
        for key in ("data", "bounties", "items", "results"):
            items = value.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    raise RuntimeError("Unexpected BountyHub response shape")


def text_of(item: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            str(item.get("title") or ""),
            str(item.get("body") or ""),
            str(item.get("additionalDescription") or ""),
            str(item.get("repositoryFullName") or ""),
        ]
    ).lower()


def base_exclusions(item: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    text = text_of(item)
    payment = str(item.get("paymentStatus") or "").upper()
    if payment != "PAID":
        reasons.append(f"not escrow-paid: {payment or 'unknown'}")
    if str(item.get("issueState") or "").lower() != "open":
        reasons.append("BountyHub issue state is not open")
    if item.get("claimed") is True:
        reasons.append("already claimed")
    if item.get("solved") is True:
        reasons.append("already solved")
    if item.get("retracted") is True:
        reasons.append("bounty retracted")
    if item.get("isFrozen") is True:
        reasons.append("bounty frozen")
    if item.get("assignee") not in (None, "", {}):
        reasons.append("BountyHub assignee already present")
    if str(item.get("assignmentType") or "open").lower() != "open":
        reasons.append("assignment is not open")
    if any(marker in text for marker in ADULT_OR_SEXUAL):
        reasons.append("adult or sexual-content project")
    if any(marker in text for marker in PHYSICAL_OR_ACCOUNT_BOUND):
        reasons.append("requires physical device, phone/account flow, or video proof")
    if any(marker in text for marker in HIGH_RISK_SECURITY):
        reasons.append("high-risk security scope")
    return sorted(set(reasons))


def github_issue(item: Mapping[str, Any]) -> tuple[str, int] | None:
    repo = str(item.get("repositoryFullName") or "").strip()
    try:
        number = int(item.get("issueNumber"))
    except (TypeError, ValueError):
        return None
    return (repo, number) if repo and number > 0 else None


def comment_attempts(comments: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    attempts: list[dict[str, str]] = []
    for comment in comments:
        body = str(comment.get("body") or "")
        lower = body.lower()
        if any(marker in lower for marker in ATTEMPT_MARKERS):
            attempts.append(
                {
                    "login": str((comment.get("user") or {}).get("login") or ""),
                    "excerpt": body[:800],
                }
            )
    return attempts


def candidate_score(
    item: Mapping[str, Any],
    repository: Mapping[str, Any],
    comments: list[Mapping[str, Any]],
    prs: list[Mapping[str, Any]],
) -> tuple[float, list[str]]:
    text = text_of(item)
    try:
        amount = float(item.get("totalAmount") or item.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    stars = int(repository.get("stargazers_count") or 0)
    score = 40.0 + min(20.0, math.log10(max(amount, 1.0)) * 8)
    reasons = ["BountyHub paymentStatus is PAID"]
    if amount <= 100:
        score += 15
        reasons.append("small first-payment-sized bounty")
    elif amount > 1000:
        score -= 25
        reasons.append("large reward likely means large scope")
    if any(marker in text for marker in SMALL_SCOPE):
        score += 20
        reasons.append("small and testable scope markers")
    if any(marker in text for marker in LARGE_SCOPE):
        score -= 35
        reasons.append("large cross-system scope")
    language = str(item.get("language") or repository.get("language") or "").lower()
    if language in {"python", "javascript", "typescript", "go", "html", "shell"}:
        score += 10
        reasons.append(f"supported language: {language}")
    elif language in {"java", "kotlin", "rust", "c++", "dm", "dart"}:
        score -= 5
        reasons.append(f"higher-cost language: {language}")
    if stars >= 100:
        score += 8
        reasons.append("established repository")
    elif stars < 5:
        score -= 12
        reasons.append("low-reputation repository")
    attempts = comment_attempts(comments)
    if attempts:
        score -= min(35, 12 * len(attempts))
        reasons.append(f"{len(attempts)} competing attempt signal(s)")
    else:
        score += 8
        reasons.append("no competing attempt signal found")
    if prs:
        score -= min(45, 15 * len(prs))
        reasons.append(f"{len(prs)} open competing PR(s)")
    else:
        score += 15
        reasons.append("no open competing PR found")
    return round(score, 2), reasons


def compact_item(
    item: Mapping[str, Any],
    issue: Mapping[str, Any] | None,
    repository: Mapping[str, Any] | None,
    comments: list[Mapping[str, Any]],
    prs: list[Mapping[str, Any]],
    exclusions: list[str],
) -> dict[str, Any]:
    score, reasons = candidate_score(item, repository or {}, comments, prs)
    return {
        "score": score,
        "score_reasons": reasons,
        "exclusions": exclusions,
        "bountyhub_id": item.get("id"),
        "title": item.get("title"),
        "amount_usd": item.get("amount"),
        "total_amount_usd": item.get("totalAmount"),
        "payment_status": item.get("paymentStatus"),
        "claimed": item.get("claimed"),
        "solved": item.get("solved"),
        "assignment_type": item.get("assignmentType"),
        "repository": item.get("repositoryFullName"),
        "issue_number": item.get("issueNumber"),
        "issue_url": item.get("htmlURL"),
        "github_issue_state": issue.get("state") if issue else None,
        "github_assignees": [
            value.get("login")
            for value in (issue.get("assignees") if issue and isinstance(issue.get("assignees"), list) else [])
            if isinstance(value, Mapping)
        ],
        "repo_stars": repository.get("stargazers_count") if repository else None,
        "repo_language": repository.get("language") if repository else item.get("language"),
        "repo_archived": repository.get("archived") if repository else None,
        "open_competing_prs": prs,
        "attempt_signals": comment_attempts(comments),
        "scope_excerpt": str(item.get("body") or "")[:3000],
        "additional_description": str(item.get("additionalDescription") or "")[:1200],
    }


def main() -> int:
    bounties = unwrap_bounties(get_json(API_URL))
    inspected: list[dict[str, Any]] = []
    for item in bounties:
        exclusions = base_exclusions(item)
        locator = github_issue(item)
        issue: dict[str, Any] | None = None
        repository: dict[str, Any] | None = None
        comments: list[dict[str, Any]] = []
        prs: list[dict[str, Any]] = []
        if locator:
            repo, number = locator
            try:
                issue_response = github.api_get(f"/repos/{repo}/issues/{number}")
                issue = issue_response.data if isinstance(issue_response.data, dict) else None
                repository = github.fetch_repo(repo)
                comments = github.fetch_comments(repo, number)
                prs = github.competing_prs(repo, number)
                if not issue or issue.get("state") != "open":
                    exclusions.append("GitHub issue is not open")
                if issue and issue.get("assignees"):
                    exclusions.append("GitHub issue already assigned")
                if repository.get("archived"):
                    exclusions.append("repository archived")
                if prs:
                    exclusions.append("open competing PR exists")
                if comment_attempts(comments):
                    exclusions.append("competing work signal exists")
            except Exception as exc:
                exclusions.append(f"GitHub validation failed: {type(exc).__name__}")
        else:
            exclusions.append("missing GitHub issue locator")
        inspected.append(
            compact_item(
                item,
                issue,
                repository,
                comments,
                prs,
                sorted(set(exclusions)),
            )
        )

    inspected.sort(key=lambda value: float(value.get("score") or -999), reverse=True)
    actionable = [item for item in inspected if not item["exclusions"]]
    output = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": API_URL,
        "safety": "read-only BountyHub and GitHub validation; no login, claim, payment, or write",
        "total_bounties": len(bounties),
        "paid_open_unclaimed_before_github_validation": sum(
            1 for item in bounties if not base_exclusions(item)
        ),
        "actionable_count": len(actionable),
        "actionable": actionable,
        "inspected": inspected,
    }
    atomic_write(OUTPUT, output)
    print(
        json.dumps(
            {
                "ok": True,
                "total": len(bounties),
                "actionable": len(actionable),
                "top": [
                    {
                        "title": item.get("title"),
                        "amount": item.get("total_amount_usd"),
                        "exclusions": item.get("exclusions"),
                    }
                    for item in inspected[:5]
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
