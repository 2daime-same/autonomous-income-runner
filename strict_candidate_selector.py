#!/usr/bin/env python3
"""Select genuinely actionable, zero-cost bounty candidates from the GitHub radar.

The upstream radar deliberately has broad recall. This selector applies a much
stricter execution policy before any issue is claimed or code is written:

* no prompt or secret exfiltration;
* no upfront payment, bond, deposit, or child-bounty funding;
* no social-media spam or public disclosure of private payout details;
* no required physical hardware/video evidence;
* no existing assignee, competing PR, or heavily contested attempt queue;
* credible reward evidence from a known platform or an established repository.

It is read-only and never comments, claims, pays, forks, or submits.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

INPUT = Path(os.environ.get("STRICT_SELECTOR_INPUT", "market-output/github-bounties.json"))
OUTPUT = Path(os.environ.get("STRICT_SELECTOR_OUTPUT", "market-output/actionable-candidates.json"))

KNOWN_SYNTHETIC_REPOS = {
    "clankernation/openagents",
    "iamgoofball/-tg-station",
    "zhangjiayang6835-cyber/bounty-plaza",
    "relayhop/claudeearnself-runtime",
    "relayhop/sn-monetization-runtime",
}

PROMPT_EXFILTRATION = (
    "system prompt",
    "hidden prompt",
    "pre-conversation instructions",
    "pre conversation instructions",
    "platform initialization text",
    "platform-provided instructions",
    "platform provided instructions",
    "full unedited text",
    "complete initialization text",
    "session start",
    "paste everything from the first token",
    "paste the full verbatim",
    "full platform initialization",
    "full initialization block",
    "developer message",
    "internal instructions",
)

UPFRONT_OUTLAY = (
    "pay a fee",
    "registration fee",
    "publication fee",
    "security deposit",
    "upfront payment",
    "claim bond",
    "fund a bounty",
    "fully fund",
    "child bounty",
    "purchase required",
    "buy credits",
    "stake required",
)

SOCIAL_OR_ABUSIVE = (
    "post on x",
    "tweet this",
    "farcaster post",
    "social media post",
    "leave a detailed review comment explaining exactly what is wrong",
    "review competing prs",
    "negative review",
    "referral link",
    "invite users",
)

PHYSICAL_EVIDENCE = (
    "video of it working",
    "record a video",
    "physical device",
    "hardware required",
    "requires hardware",
    "on-device test",
    "apple silicon only",
)

PRIVATE_PAYOUT_DISCLOSURE = (
    "payment details again",
    "wallet address in the pr",
    "wallet address in the issue",
    "paypal email in the issue",
    "publicly post your wallet",
)

LARGE_SCOPE = (
    "build an entire",
    "full rewrite",
    "complete rewrite",
    "new programming language",
    "production backend",
    "mobile application",
    "browser extension",
    "operating system",
    "blockchain protocol",
    "smart contract audit",
    "security audit",
    "new game mode",
    "all files must be translated",
)

SMALL_SCOPE_MARKERS = (
    "documentation",
    "readme",
    "typo",
    "error message",
    "validation",
    "unit test",
    "test harness",
    "missing test",
    "small fix",
    "one-line",
    "one line",
    "cli flag",
    "null check",
    "edge case",
    "pagination",
    "regex",
    "duplicate",
    "fallback",
    "serialization",
    "deserialization",
)

KNOWN_PLATFORM_BOTS = {
    "algora-pbc[bot]",
    "opire-bot",
    "opire[bot]",
    "issuehunt[bot]",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def candidate_text(candidate: Mapping[str, Any]) -> str:
    evidence = candidate.get("reward_evidence")
    comment_parts: list[str] = []
    if isinstance(evidence, Mapping):
        for key in ("direct_comments", "bot_comments"):
            entries = evidence.get(key)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, Mapping):
                        comment_parts.append(str(entry.get("excerpt") or ""))
    labels = candidate.get("labels") if isinstance(candidate.get("labels"), list) else []
    return "\n".join(
        [
            str(candidate.get("title") or ""),
            str(candidate.get("body_excerpt") or ""),
            " ".join(str(label) for label in labels),
            *comment_parts,
        ]
    ).lower()


def known_platform_evidence(candidate: Mapping[str, Any]) -> bool:
    evidence = candidate.get("reward_evidence")
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("explicit_platform") is True:
        return True
    entries = evidence.get("direct_comments")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("known_platform_bot") is True:
                return True
            if str(entry.get("login") or "").lower() in KNOWN_PLATFORM_BOTS:
                return True
    return False


def safety_flags(candidate: Mapping[str, Any]) -> list[str]:
    text = candidate_text(candidate)
    flags: list[str] = []
    repo = str(candidate.get("repo") or "").lower()
    evidence = candidate.get("reward_evidence") if isinstance(candidate.get("reward_evidence"), Mapping) else {}
    amount = float(evidence.get("max_amount_usd") or 0.0)
    attempts = int(evidence.get("attempt_count") or 0)
    author = str(candidate.get("issue_author") or "")

    if repo in KNOWN_SYNTHETIC_REPOS:
        flags.append("known synthetic or adversarial bounty repository")
    if any(phrase in text for phrase in PROMPT_EXFILTRATION):
        flags.append("requests hidden prompts, internal instructions, or session metadata")
    if any(phrase in text for phrase in UPFRONT_OUTLAY):
        flags.append("requires an upfront outlay, bond, deposit, or funded child task")
    if any(phrase in text for phrase in SOCIAL_OR_ABUSIVE):
        flags.append("requires social spam or adversarial review activity")
    if any(phrase in text for phrase in PHYSICAL_EVIDENCE):
        flags.append("requires physical hardware or video evidence unavailable to the agent")
    if any(phrase in text for phrase in PRIVATE_PAYOUT_DISCLOSURE):
        flags.append("requires private payout details to be posted publicly")
    if amount > 1_000:
        flags.append("reward is unusually high for the first-income target")
    if attempts > 2:
        flags.append("more than two competing attempt users")
    if candidate.get("assignees"):
        flags.append("issue is already assigned")
    if candidate.get("open_competing_prs"):
        flags.append("an open competing pull request already exists")
    if candidate.get("repo_fork") is True:
        flags.append("repository is a fork")
    if candidate.get("repo_archived") is True:
        flags.append("repository is archived")
    if evidence.get("direct_reward_evidence") is not True:
        flags.append("no direct reward evidence")
    if int(evidence.get("reward_links_count") or 0) > 0:
        flags.append("existing reward links indicate the task may already be claimed")
    if author.endswith("[bot]") and not known_platform_evidence(candidate):
        flags.append("bot-authored issue without recognized platform evidence")

    repo_created = parse_time(candidate.get("repo_created_at"))
    repo_age_days = (datetime.now(timezone.utc) - repo_created).days if repo_created else 9999
    stars = int(candidate.get("repo_stars") or 0)
    owner_type = str(candidate.get("repo_owner_type") or "")
    if not known_platform_evidence(candidate):
        if stars < 10 and owner_type != "Organization":
            flags.append("unrecognized platform on a low-reputation personal repository")
        if repo_age_days < 90:
            flags.append("unrecognized platform on a repository younger than 90 days")

    return sorted(set(flags))


def scope_score(candidate: Mapping[str, Any]) -> tuple[float, list[str]]:
    text = candidate_text(candidate)
    evidence = candidate.get("reward_evidence") if isinstance(candidate.get("reward_evidence"), Mapping) else {}
    amount = float(evidence.get("max_amount_usd") or 0.0)
    score = float(candidate.get("score") or 0.0)
    reasons: list[str] = []

    score += min(20.0, math.log10(max(1.0, amount)) * 8)
    if known_platform_evidence(candidate):
        score += 25
        reasons.append("recognized bounty platform evidence")
    if any(marker in text for marker in SMALL_SCOPE_MARKERS):
        score += 18
        reasons.append("small, testable implementation markers")
    if any(marker in text for marker in LARGE_SCOPE):
        score -= 35
        reasons.append("large implementation scope")
    language = str(candidate.get("repo_language") or "").lower()
    if language in {"python", "javascript", "typescript", "html", "shell", "go"}:
        score += 8
        reasons.append(f"supported implementation language: {language}")
    if language in {"solidity", "move", "rust", "c++", "objective-c"}:
        score -= 8
        reasons.append(f"higher-cost implementation language: {language}")
    comments = int(candidate.get("comments_count") or 0)
    if comments <= 5:
        score += 5
    return round(score, 2), reasons


def compact_candidate(candidate: Mapping[str, Any], selector_score: float, reasons: list[str]) -> dict[str, Any]:
    evidence = candidate.get("reward_evidence") if isinstance(candidate.get("reward_evidence"), Mapping) else {}
    return {
        "selector_score": selector_score,
        "selector_reasons": reasons,
        "repo": candidate.get("repo"),
        "issue_number": candidate.get("issue_number"),
        "title": candidate.get("title"),
        "url": candidate.get("url"),
        "reward_usd": evidence.get("max_amount_usd"),
        "repo_language": candidate.get("repo_language"),
        "repo_stars": candidate.get("repo_stars"),
        "repo_created_at": candidate.get("repo_created_at"),
        "updated_at": candidate.get("updated_at"),
        "comments_count": candidate.get("comments_count"),
        "attempt_count": evidence.get("attempt_count"),
        "known_platform_evidence": known_platform_evidence(candidate),
        "body_excerpt": str(candidate.get("body_excerpt") or "")[:2500],
        "reward_evidence": {
            "direct_reward_evidence": evidence.get("direct_reward_evidence"),
            "explicit_platform": evidence.get("explicit_platform"),
            "direct_comments": evidence.get("direct_comments", [])[:3] if isinstance(evidence.get("direct_comments"), list) else [],
        },
    }


def main() -> int:
    report = read_json(INPUT)
    ranked = report.get("ranked_candidates")
    if not isinstance(ranked, list):
        raise ValueError("Input radar report has no ranked_candidates array")

    actionable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in ranked:
        if not isinstance(raw, Mapping):
            continue
        flags = safety_flags(raw)
        if flags:
            excluded.append(
                {
                    "repo": raw.get("repo"),
                    "issue_number": raw.get("issue_number"),
                    "title": raw.get("title"),
                    "url": raw.get("url"),
                    "flags": flags,
                }
            )
            continue
        score, reasons = scope_score(raw)
        actionable.append(compact_candidate(raw, score, reasons))

    actionable.sort(key=lambda item: float(item.get("selector_score") or -999), reverse=True)
    output = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_generated_at": report.get("generated_at"),
        "policy": "zero-cost, no prompt exfiltration, no social spam, no physical-only proof, no active competitor",
        "input_candidate_count": len(ranked),
        "actionable_count": len(actionable),
        "actionable": actionable[:25],
        "excluded_count": len(excluded),
        "excluded": excluded[:100],
    }
    atomic_write(OUTPUT, output)
    print(json.dumps({"ok": True, "actionable": len(actionable), "excluded": len(excluded)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
