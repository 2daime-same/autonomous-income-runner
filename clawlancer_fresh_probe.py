#!/usr/bin/env python3
"""Read-only compact probe for currently claimable Clawlancer micro-bounties."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE = "https://clawlancer.ai/api"
OUTPUT = Path("clawlancer-fresh-output/inventory.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_json(path: str) -> tuple[int, Any]:
    req = urllib.request.Request(
        BASE + path,
        headers={"Accept": "application/json", "User-Agent": "boundaryledger-clawlancer-fresh-probe/2.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read(20_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"text": raw[:1000]}
        return exc.code, payload


def unwrap(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("listings", "data", "items", "results"):
            if isinstance(value.get(key), list):
                return [dict(item) for item in value[key] if isinstance(item, Mapping)]
    return []


def reward_usdc(item: Mapping[str, Any]) -> float:
    value = item.get("price_wei") or item.get("priceWei") or item.get("price") or 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / 1_000_000 if number > 1000 else number


def safe_candidate(item: Mapping[str, Any]) -> bool:
    if str(item.get("listing_type") or item.get("listingType") or "").upper() != "BOUNTY":
        return False
    if item.get("is_active") is False:
        return False
    if str(item.get("status") or "active").lower() not in {"active", "open"}:
        return False
    reward = reward_usdc(item)
    if not (0 < reward <= 0.10):
        return False
    text = f"{item.get('title', '')}\n{item.get('description', '')}".lower()
    blocked = (
        "tweet", "post on x", "referral", "follow ", "like ", "send usdc", "deposit",
        "purchase", "buy ", "wallet connect", "seed phrase", "private key", "kyc",
        "adult", "sexual", "nsfw", "malware", "exploit", "credential theft",
    )
    return not any(marker in text for marker in blocked)


def compact(item: Mapping[str, Any]) -> dict[str, Any]:
    agent = item.get("agent") if isinstance(item.get("agent"), Mapping) else {}
    description = re.sub(r"\s+", " ", str(item.get("description") or "")).strip()
    return {
        "id": str(item.get("id") or "")[:100],
        "title": str(item.get("title") or "")[:500],
        "description": description[:2000],
        "reward_usdc": reward_usdc(item),
        "status": str(item.get("status") or ""),
        "is_active": item.get("is_active"),
        "category": str(item.get("category") or "")[:100],
        "created_at": item.get("created_at") or item.get("createdAt"),
        "buyer": {
            "id_hash": __import__("hashlib").sha256(str(agent.get("id") or "").encode()).hexdigest()[:16],
            "name": str(agent.get("name") or "")[:200],
            "completed_transactions": agent.get("completed_transactions") or agent.get("total_completed"),
            "payment_rate": agent.get("payment_rate") or agent.get("paymentRate"),
            "disputes": agent.get("disputes") or agent.get("dispute_count"),
        },
    }


def main() -> int:
    status, payload = get_json("/listings?listing_type=BOUNTY&limit=100")
    items = unwrap(payload)
    candidates = [compact(item) for item in items if safe_candidate(item)]
    candidates.sort(key=lambda item: (-float(item["reward_usdc"]), str(item.get("created_at") or "")), reverse=False)
    result = {
        "generated_at": now_iso(),
        "endpoint": BASE + "/listings?listing_type=BOUNTY&limit=100",
        "http_status": status,
        "listing_count": len(items),
        "safe_claimable_count": len(candidates),
        "safe_claimable": candidates,
        "authentication_used": False,
        "writes_performed": [],
        "expenses_usdc": 0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"ok": status == 200, "listings": len(items), "safe": len(candidates)}))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
