#!/usr/bin/env python3
"""Create a fast one-call snapshot of currently open Archimedes bounties."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import archimedes_live_search as mcp

OUTPUT = Path(os.environ.get("ARCHIMEDES_FAST_OUTPUT", "market-output/archimedes-open-summary.json"))
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def walk(value: Any):
    yield value
    if isinstance(value, Mapping):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def records(value: Any) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in walk(value):
        if not isinstance(item, Mapping):
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not UUID_RE.fullmatch(identifier):
            continue
        if not isinstance(item.get("title"), str):
            continue
        if not isinstance(item.get("price_cents"), (int, float)):
            continue
        url = item.get("url")
        if not isinstance(url, str) or "/bounties/" not in url:
            continue
        by_id[identifier.lower()] = dict(item)
    return sorted(
        by_id.values(),
        key=lambda item: (-int(item.get("price_cents") or 0), str(item.get("display_id") or "")),
    )


def main() -> int:
    response = mcp.rpc(
        "tools/call",
        {
            "name": "search_bounties",
            "arguments": {"status": "open", "limit": 50, "offset": 0},
        },
        1,
    )
    decoded = mcp.decode_embedded_json(mcp.result_value(response))
    items = records(decoded)
    total_cents = sum(int(item.get("price_cents") or 0) for item in items)
    output = {
        "schema_version": "archimedes-open-summary-v1",
        "generated_at": iso_now(),
        "source": mcp.ENDPOINT,
        "mode": "public_read_only_one_call",
        "open_bounty_count": len(items),
        "open_payout_total_cents": total_cents,
        "open_payout_total_usd": round(total_cents / 100, 2),
        "items": items,
        "commercial_status": {
            "verified_income_usd": 0,
            "verified_receivable_usd": 0,
            "expenses_usd": 0,
            "submission_performed": False,
            "account_action_performed": False,
        },
        "response_sha256": hashlib.sha256(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    mcp.assert_public_output(output)
    mcp.atomic_json(OUTPUT, output)
    print(json.dumps({
        "ok": True,
        "open_bounty_count": len(items),
        "open_payout_total_usd": output["open_payout_total_usd"],
        "display_ids": [item.get("display_id") for item in items],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
