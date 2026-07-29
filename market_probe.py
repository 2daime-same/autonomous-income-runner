#!/usr/bin/env python3
"""Read-only probe for paid-work markets with machine-checkable settlement.

The probe never registers, claims, signs, pays, posts, or submits. It fetches
public JSON and reduces it to an evidence-oriented opportunity snapshot.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path(os.environ.get("MARKET_OUTPUT_FILE", "market-output/latest.json"))
TIMEOUT = 45
SOURCES = {
    "agent_bounties": "https://api.agentbounties.app/v1/opportunities",
    "agent_bounties_inventory": "https://api.agentbounties.app/v1/base/autonomous-bounties/inventory-summary?network=base-mainnet&claimable_only=true",
    "botbounty": "https://botbounty-production.up.railway.app/api/agent/bounties",
    "moltguild": "https://agent-bounty-production.up.railway.app/api/jobs?status=open",
    "taskbounty": "https://www.task-bounty.com/api/v1/tasks?state=open&limit=100",
    "hackmates_status": "https://www.hackmates.xyz/api/sandbox/status",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def get_json(url: str, retries: int = 2) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "autonomous-income-runner-market-probe/1.1",
        },
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            if exc.code < 500 or attempt >= retries:
                raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt >= retries:
                break
        time.sleep(2**attempt)
    raise RuntimeError(str(last))


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def token_amount(value: Any) -> float | None:
    if not isinstance(value, Mapping):
        return None
    try:
        amount = int(str(value.get("amount")))
        decimals = int(value.get("decimals", 0))
    except (TypeError, ValueError):
        return None
    return amount / (10**decimals)


def compact_agent_bounty(item: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    deadline = parse_time(item.get("deadline"))
    evidence = item.get("evidence_requirements")
    required: list[str] = []
    if isinstance(evidence, Mapping) and isinstance(evidence.get("required"), list):
        required = [str(x) for x in evidence["required"]]

    title = str(item.get("title") or "")
    goal = str(item.get("goal") or "")
    text = f"{title} {goal} {' '.join(required)}".lower()
    child_funding = (
        "child bounty" in text
        or "child_bounty_contract" in text
        or ("fully fund" in text and "bounty" in text)
    )
    social_action = any(
        marker in text
        for marker in (
            "post on x",
            "tweet",
            "farcaster",
            "social media",
            "referral",
        )
    )

    bond = token_amount(item.get("bond"))
    reward = token_amount(item.get("reward"))
    claimable = (
        item.get("source_status") == "claimable"
        and item.get("work_state") == "claimable"
        and item.get("payment_state") == "escrowed"
        and item.get("payment_committed") is True
        and item.get("verification_ready") is True
        and (deadline is None or deadline > now)
    )
    zero_bond = bond in (None, 0.0)
    no_detected_outlay = not child_funding and not social_action

    return {
        "opportunity_id": item.get("opportunity_id"),
        "contract": item.get("source_id"),
        "title": title,
        "goal": goal,
        "public_url": item.get("public_url"),
        "source_status": item.get("source_status"),
        "work_state": item.get("work_state"),
        "payment_state": item.get("payment_state"),
        "payment_committed": item.get("payment_committed"),
        "competition_mode": item.get("competition_mode"),
        "standing_meta_bounty": item.get("standing_meta_bounty"),
        "verification_method": item.get("verification_method"),
        "verification_ready": item.get("verification_ready"),
        "reward_usdc": reward,
        "bond_usdc": bond,
        "deadline": item.get("deadline"),
        "deadline_future": deadline is None or deadline > now,
        "required_evidence": required,
        "detected_child_funding": child_funding,
        "detected_social_action": social_action,
        "claimable_paid_candidate": claimable,
        "zero_cost_candidate": claimable and zero_bond and no_detected_outlay,
        "low_cost_candidate": claimable and (bond or 0.0) <= 0.01 and no_detected_outlay,
        "next_action": item.get("next_action"),
    }


def summarize_agent_bounties(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("items"), list):
        raise RuntimeError("Unexpected Agent Bounties response shape")
    now = datetime.now(timezone.utc)
    items = [
        compact_agent_bounty(item, now)
        for item in value["items"]
        if isinstance(item, Mapping)
    ]
    claimable = [item for item in items if item["claimable_paid_candidate"]]
    zero_cost = [item for item in claimable if item["zero_cost_candidate"]]
    low_cost = [item for item in claimable if item["low_cost_candidate"]]
    return {
        "schema_version": value.get("schema_version"),
        "generated_at": value.get("generated_at"),
        "total_items": len(items),
        "claimable_paid_count": len(claimable),
        "zero_cost_count": len(zero_cost),
        "low_cost_count": len(low_cost),
        "zero_cost_candidates": zero_cost,
        "low_cost_candidates": low_cost,
        "all_claimable_paid_candidates": claimable,
    }


def unwrap_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        for key in ("data", "items", "bounties", "jobs", "results", "tasks", "hunts"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
    return []


def generic_market_summary(value: Any) -> dict[str, Any]:
    items = unwrap_list(value)
    compact: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        compact.append(
            {
                key: raw.get(key)
                for key in (
                    "id",
                    "task_id",
                    "title",
                    "name",
                    "status",
                    "state",
                    "reward",
                    "reward_amount",
                    "bounty_cents",
                    "budget",
                    "budget_usdc",
                    "deadline",
                    "github_repo_url",
                    "github_issue_url",
                    "language",
                    "complexity_tag",
                    "url",
                    "slug",
                    "description",
                )
                if raw.get(key) is not None
            }
        )
    scalar_summary = None
    if not items and isinstance(value, Mapping):
        scalar_summary = {
            str(key): raw
            for key, raw in value.items()
            if isinstance(raw, (str, int, float, bool)) or raw is None
        }
    return {
        "count": len(items),
        "items": compact[:100],
        "raw_shape": type(value).__name__,
        "scalar_summary": scalar_summary,
    }


def main() -> int:
    report: dict[str, Any] = {"generated_at": now_iso(), "sources": {}}
    raw_agent_bounties: Any = None
    for name, url in SOURCES.items():
        try:
            value = get_json(url)
            if name == "agent_bounties":
                raw_agent_bounties = value
                summary = summarize_agent_bounties(value)
            elif name == "agent_bounties_inventory":
                summary = value
            else:
                summary = generic_market_summary(value)
            report["sources"][name] = {"ok": True, "url": url, "summary": summary}
        except Exception as exc:  # network/API evidence must survive partial failure
            report["sources"][name] = {"ok": False, "url": url, "error": str(exc)}

    if raw_agent_bounties is not None:
        report["priority"] = report["sources"]["agent_bounties"]["summary"]
    atomic_write(OUTPUT, report)
    print(json.dumps({"ok": True, "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
