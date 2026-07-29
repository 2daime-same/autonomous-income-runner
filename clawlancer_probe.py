#!/usr/bin/env python3
"""Read-only inspection of Clawlancer public inventory and API shapes."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE = "https://clawlancer.ai/api"
OUTPUT = Path(os.environ.get("CLAWLANCER_PROBE_OUTPUT", "clawlancer-output/live-probe.json"))
TIMEOUT = 45
SECRET_KEYS = {"api_key", "apikey", "private_key", "secret", "token", "authorization"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            result[key] = "[REDACTED]" if normalized in SECRET_KEYS else sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\b(?:claw|cl|api)_[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    return value


def request(method: str, path: str) -> dict[str, Any]:
    url = BASE + path
    req = urllib.request.Request(
        url,
        method=method,
        headers={"Accept": "application/json", "User-Agent": "nexaworks-clawlancer-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read(4_000_000).decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw[:20_000]
            return {
                "ok": True,
                "status": response.status,
                "url": response.geturl(),
                "headers": {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower() in {"allow", "content-type", "x-ratelimit-limit", "x-ratelimit-remaining"}
                },
                "payload": sanitize(payload),
            }
    except urllib.error.HTTPError as error:
        raw = error.read(20_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return {
            "ok": False,
            "status": error.code,
            "url": url,
            "headers": {
                key.lower(): value
                for key, value in error.headers.items()
                if key.lower() in {"allow", "content-type", "x-ratelimit-limit", "x-ratelimit-remaining"}
            },
            "payload": sanitize(payload),
        }
    except Exception as error:
        return {"ok": False, "url": url, "error": f"{type(error).__name__}: {error}"}


def unwrap_list(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "listings", "items", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
    return []


def main() -> int:
    endpoints: dict[str, Any] = {
        "info": request("GET", "/info"),
        "health": request("GET", "/health"),
        "stats": request("GET", "/stats"),
        "bounties": request("GET", "/listings?listing_type=BOUNTY&limit=100"),
        "register_options": request("OPTIONS", "/agents/register"),
    }
    items = unwrap_list(endpoints["bounties"].get("payload"))
    selected = []
    for item in items:
        title = str(item.get("title") or "")
        description = str(item.get("description") or "")
        listing_type = str(item.get("listing_type") or item.get("listingType") or item.get("type") or "")
        price = item.get("price") or item.get("price_wei") or item.get("priceWei") or item.get("amount")
        text = f"{title}\n{description}".lower()
        blocked = any(marker in text for marker in ("post on x", "tweet", "referral", "buy ", "purchase", "send usdc", "deposit"))
        if listing_type.upper() == "BOUNTY" and not blocked:
            selected.append({
                "id": item.get("id"),
                "title": title,
                "description": description,
                "price": price,
                "category": item.get("category"),
                "status": item.get("status"),
                "poster": sanitize(item.get("seller") or item.get("poster") or item.get("agent")),
                "raw": sanitize(item),
            })
    selected.sort(key=lambda x: (str(x.get("price")), str(x.get("title"))))
    result = {
        "generated_at": now_iso(),
        "endpoints": endpoints,
        "listing_count": len(items),
        "safe_bounty_count": len(selected),
        "safe_bounties": selected[:30],
        "writes_performed": [],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"ok": True, "listings": len(items), "safe_bounties": len(selected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
