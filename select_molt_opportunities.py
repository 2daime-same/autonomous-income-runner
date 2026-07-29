#!/usr/bin/env python3
"""Select currently actionable, zero-outlay Molt-family opportunities.

Input is the primary-source probe output. Examples embedded in documentation are
never treated as inventory. Referral, social-promotion, deposit/bond, and
self-funding tasks are excluded.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path(os.environ.get("MOLT_MARKET_SOURCE", "market-output/molt-markets.json"))
OUTPUT = Path(os.environ.get("MOLT_OPPORTUNITY_OUTPUT", "market-output/molt-opportunities.json"))

BLOCKED_MARKERS = (
    "refer ",
    "referral",
    "invite ",
    "post on x",
    "tweet",
    "social media",
    "viral",
    "marketing campaign",
    "bring new agents",
    "town square",
    "guestbook",
    "external_post",
    "fund a bounty",
    "fully fund",
    "deposit",
    "bond required",
    "purchase",
    "pay first",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def as_items(endpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    inventory = endpoint.get("inventory")
    if not isinstance(inventory, Mapping):
        return []
    items = inventory.get("items")
    return [dict(item) for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []


def flatten_text(item: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "name",
        "description",
        "category",
        "acceptance_criteria",
        "skills",
        "tags",
        "verification_template",
    ):
        value = item.get(key)
        if isinstance(value, list):
            parts.extend(str(entry) for entry in value)
        elif value is not None:
            parts.append(str(value))
    return "\n".join(parts).lower()


def amount_hint(item: Mapping[str, Any]) -> Any:
    for key in (
        "budgetUsdc",
        "budget_usdc",
        "pay_usdc",
        "budget",
        "bounty_cents",
        "bounty_amount",
        "reward_amount",
        "reward",
    ):
        if item.get(key) is not None:
            return item.get(key)
    return None


def status_open(item: Mapping[str, Any]) -> bool:
    status = str(item.get("status") or item.get("state") or "").strip().lower()
    return status in {"open", "available", "active", "posted", "funded", "claimable"} or not status


def candidate(source: str, item: Mapping[str, Any]) -> dict[str, Any]:
    text = flatten_text(item)
    blockers = [marker for marker in BLOCKED_MARKERS if marker in text]
    return {
        "source": source,
        "id": item.get("id") or item.get("slug"),
        "title": item.get("title") or item.get("name"),
        "description": item.get("description"),
        "status": item.get("status") or item.get("state"),
        "amount_hint": amount_hint(item),
        "deadline": item.get("deadline") or item.get("deadlineAt"),
        "skills": item.get("skills") or item.get("required_skills"),
        "category": item.get("category") or item.get("vertical"),
        "acceptance_criteria": item.get("acceptance_criteria"),
        "url": item.get("url"),
        "blockers": blockers,
        "actionable_without_outlay": status_open(item) and not blockers,
    }


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    endpoints = data.get("endpoints") if isinstance(data, Mapping) else None
    if not isinstance(endpoints, Mapping):
        raise RuntimeError("Missing endpoints object")

    inventory_sources = {
        "moltjobs_io": "moltjobs_io_jobs",
        "molt_jobs_com": "molt_jobs_jobs_v1",
        "moltask": "moltask_bounties",
        "moltask_asks": "moltask_asks",
        "moltcities": "moltcities_jobs",
    }
    inspected: list[dict[str, Any]] = []
    for source, endpoint_name in inventory_sources.items():
        endpoint = endpoints.get(endpoint_name)
        if not isinstance(endpoint, Mapping):
            continue
        for item in as_items(endpoint):
            inspected.append(candidate(source, item))

    actionable = [item for item in inspected if item["actionable_without_outlay"]]
    excluded = [item for item in inspected if not item["actionable_without_outlay"]]

    source_status = {}
    for name, endpoint in endpoints.items():
        if not isinstance(endpoint, Mapping):
            continue
        inventory = endpoint.get("inventory")
        source_status[name] = {
            "http_status": endpoint.get("status"),
            "ok": endpoint.get("ok"),
            "item_count": inventory.get("item_count") if isinstance(inventory, Mapping) else None,
            "error": (inventory.get("scalar") or {}).get("error") if isinstance(inventory, Mapping) and isinstance(inventory.get("scalar"), Mapping) else endpoint.get("error"),
        }

    result = {
        "generated_at": now_iso(),
        "source_generated_at": data.get("generated_at") if isinstance(data, Mapping) else None,
        "source_status": source_status,
        "inspected_count": len(inspected),
        "actionable_count": len(actionable),
        "actionable": actionable,
        "excluded_count": len(excluded),
        "excluded_examples": excluded[:50],
        "policy": {
            "documentation_examples_are_not_inventory": True,
            "referral_and_social_tasks_excluded": True,
            "outlay_required_tasks_excluded": True,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "inspected": len(inspected), "actionable": len(actionable), "top": actionable[:5]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
