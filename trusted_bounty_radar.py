#!/usr/bin/env python3
"""Find small, current GitHub bounties backed by traceable payment programs.

Unlike the broad discovery radar, this module searches specifically for known
payment systems or established project bounty labels. It rejects prompt
exfiltration, upfront spending, assigned work, competing PRs, and physical-only
proof requirements before writing a shortlist.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import github_bounty_radar as broad
import strict_candidate_selector as strict

OUTPUT = Path(os.environ.get("TRUSTED_BOUNTY_OUTPUT", "market-output/trusted-bounties.json"))

QUERIES = [
    'is:issue is:open "algora.io"',
    'is:issue is:open "opire.dev"',
    'is:issue is:open "oss.issuehunt.io"',
    'is:issue is:open "IssueHunt Summary"',
    'is:issue is:open label:"$$ bug-bounty $$"',
    'is:issue is:open "BountySource"',
    'is:issue is:open "gitwork:usdc:"',
    'is:issue is:open "gitwork:sol:"',
    'is:issue is:open "gitwork.io" bounty',
    'is:issue is:open "bountyhub.dev"',
    'is:issue is:open "codebounty.org"',
    'is:issue is:open "bounty-hub.vercel.app"',
]

TRUST_MARKERS = {
    "algora": ("algora.io", "algora-pbc[bot]", "algora-pbc"),
    "opire": ("opire.dev", "opire-bot", "opire[bot]"),
    "issuehunt": ("oss.issuehunt.io", "issuehunt[bot]", "issuehunt summary"),
    "jhipster": ("$$ bug-bounty $$", "jhipster.tech/bug-bounties"),
    "bountysource": ("bountysource.com", "bountysource"),
    "gitwork": ("gitwork:usdc:", "gitwork:sol:", "gitwork.io"),
    "bountyhub": ("bountyhub.dev/bounty/", "bountyhub.dev/en/bounty/", "bountyhub.dev"),
    "codebounty": ("codebounty.org",),
    "onchain_bountyhub": ("bounty-hub.vercel.app",),
}

DIRECT_LABEL_PATTERNS = (
    re.compile(r"^gitwork:(?:usdc|sol):[0-9]+(?:\.[0-9]+)?$", re.I),
    re.compile(r"^\$\$ bug-bounty \$\$$", re.I),
    re.compile(r"^\$[0-9]+(?:\.[0-9]+)?$"),
)

DIRECT_URL_MARKERS = (
    "algora.io/",
    "opire.dev/",
    "oss.issuehunt.io/",
    "bountyhub.dev/en/bounty/",
    "bountyhub.dev/bounty/",
    "codebounty.org/bount",
    "bounty-hub.vercel.app/",
    "gitwork.io/bount",
)


def atomic_write(path: Path, value: Any) -> None:
    strict.atomic_write(path, value)


def combined_text(issue: Mapping[str, Any], comments: list[Mapping[str, Any]]) -> str:
    labels = broad.label_names(issue)
    text_parts = [
        str(issue.get("title") or ""),
        str(issue.get("body") or ""),
        " ".join(labels),
    ]
    for comment in comments:
        text_parts.append(str(comment.get("body") or ""))
        text_parts.append(str((comment.get("user") or {}).get("login") or ""))
    return "\n".join(text_parts).lower()


def trust_program(issue: Mapping[str, Any], comments: list[Mapping[str, Any]]) -> list[str]:
    text = combined_text(issue, comments)
    return sorted(
        program
        for program, markers in TRUST_MARKERS.items()
        if any(marker.lower() in text for marker in markers)
    )


def has_program_direct_evidence(
    issue: Mapping[str, Any],
    comments: list[Mapping[str, Any]],
    programs: list[str],
    amount: float,
) -> bool:
    """Require a program-specific URL/bot/label plus a non-zero reward.

    This deliberately does not trust a generic sentence that merely compares
    bounty platforms. Evidence must occur in the actual issue, labels, or a
    platform-generated comment.
    """
    if amount <= 0 or not programs:
        return False
    labels = broad.label_names(issue)
    if any(pattern.match(label.strip()) for label in labels for pattern in DIRECT_LABEL_PATTERNS):
        if "gitwork" in programs or "jhipster" in programs:
            return True
    issue_text = "\n".join(
        [str(issue.get("title") or ""), str(issue.get("body") or ""), " ".join(labels)]
    ).lower()
    if any(marker in issue_text for marker in DIRECT_URL_MARKERS):
        return True
    for comment in comments:
        login = str((comment.get("user") or {}).get("login") or "").lower()
        body = str(comment.get("body") or "").lower()
        if login in {
            "algora-pbc[bot]",
            "algora-pbc",
            "opire-bot",
            "opire[bot]",
            "issuehunt[bot]",
        }:
            return True
        if any(marker in body for marker in DIRECT_URL_MARKERS):
            return True
    return False


def compact_issue(
    issue: Mapping[str, Any],
    comments: list[Mapping[str, Any]],
    repository: Mapping[str, Any],
    prs: list[Mapping[str, Any]],
) -> dict[str, Any]:
    evidence = broad.reward_evidence(issue, comments)
    programs = trust_program(issue, comments)
    amount = float(evidence.get("max_amount_usd") or 0.0)
    if has_program_direct_evidence(issue, comments, programs, amount):
        evidence = dict(evidence)
        evidence["direct_reward_evidence"] = True

    candidate = {
        "score": 0,
        "repo": broad.repo_from_issue(issue),
        "repo_language": repository.get("language"),
        "repo_stars": repository.get("stargazers_count"),
        "repo_fork": repository.get("fork"),
        "repo_archived": repository.get("archived"),
        "repo_owner_type": (repository.get("owner") or {}).get("type"),
        "repo_created_at": repository.get("created_at"),
        "issue_author": (issue.get("user") or {}).get("login"),
        "issue_number": issue.get("number"),
        "title": issue.get("title"),
        "url": issue.get("html_url"),
        "updated_at": issue.get("updated_at"),
        "comments_count": issue.get("comments"),
        "assignees": [
            entry.get("login")
            for entry in issue.get("assignees", [])
            if isinstance(entry, Mapping)
        ],
        "open_competing_prs": prs,
        "labels": broad.label_names(issue),
        "body_excerpt": str(issue.get("body") or "")[:4000],
        "reward_evidence": evidence,
    }
    flags = strict.safety_flags(candidate)
    scope, scope_reasons = strict.scope_score(candidate)
    score = scope + 15 * len(programs)
    if 1 <= amount <= 100:
        score += 12
        scope_reasons.append("small first-payment-sized reward")
    elif amount > 500:
        score -= 12
        scope_reasons.append("larger reward likely implies larger scope")
    return {
        "selector_score": round(score, 2),
        "selector_reasons": scope_reasons,
        "trust_programs": programs,
        "safety_flags": flags,
        "repo": candidate["repo"],
        "issue_number": candidate["issue_number"],
        "title": candidate["title"],
        "url": candidate["url"],
        "reward_usd": amount,
        "repo_language": candidate["repo_language"],
        "repo_stars": candidate["repo_stars"],
        "updated_at": candidate["updated_at"],
        "assignees": candidate["assignees"],
        "open_competing_prs": prs,
        "attempt_count": evidence.get("attempt_count"),
        "body_excerpt": candidate["body_excerpt"],
        "direct_reward_evidence": evidence.get("direct_reward_evidence"),
        "direct_comments": (
            evidence.get("direct_comments", [])[:5]
            if isinstance(evidence.get("direct_comments"), list)
            else []
        ),
    }


def main() -> int:
    raw: dict[str, dict[str, Any]] = {}
    query_errors: list[dict[str, str]] = []
    for query in QUERIES:
        try:
            for issue in broad.search_issues(query, pages=3):
                if broad.is_pr_reference(issue):
                    continue
                url = str(issue.get("html_url") or "")
                if url:
                    raw[url] = issue
        except Exception as exc:
            query_errors.append({"query": query, "error": str(exc)})

    inspected: list[dict[str, Any]] = []
    repo_cache: dict[str, dict[str, Any]] = {}
    for issue in sorted(raw.values(), key=broad.pre_score, reverse=True)[:180]:
        repo = broad.repo_from_issue(issue)
        number = issue.get("number")
        if not repo or not isinstance(number, int):
            continue
        try:
            comments = broad.fetch_comments(repo, number)
            programs = trust_program(issue, comments)
            if not programs:
                continue
            repository = repo_cache.setdefault(repo, broad.fetch_repo(repo))
            prs = broad.competing_prs(repo, number)
            inspected.append(compact_issue(issue, comments, repository, prs))
        except Exception as exc:
            inspected.append(
                {
                    "repo": repo,
                    "issue_number": number,
                    "title": issue.get("title"),
                    "url": issue.get("html_url"),
                    "inspection_error": str(exc),
                    "safety_flags": ["inspection failed"],
                }
            )

    inspected.sort(
        key=lambda item: float(item.get("selector_score") or -999), reverse=True
    )
    actionable = [
        item
        for item in inspected
        if not item.get("safety_flags")
        and item.get("trust_programs")
        and item.get("direct_reward_evidence") is True
        and 1 <= float(item.get("reward_usd") or 0.0) <= 1_000
    ]
    output = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "GitHub REST primary issue, comment, repository, and pull-request evidence",
        "queries": QUERIES,
        "query_errors": query_errors,
        "raw_unique_open_issues": len(raw),
        "inspected_count": len(inspected),
        "actionable_count": len(actionable),
        "actionable": actionable[:40],
        "inspected": inspected[:180],
    }
    atomic_write(OUTPUT, output)
    print(
        json.dumps(
            {
                "ok": True,
                "raw": len(raw),
                "inspected": len(inspected),
                "actionable": len(actionable),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
