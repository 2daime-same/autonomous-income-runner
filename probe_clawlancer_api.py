#!/usr/bin/env python3
"""Inspect Clawlancer's public API and documentation without registering or claiming."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://clawlancer.ai"
OUTPUT = Path(os.environ.get("CLAWLANCER_PROBE_OUTPUT", "market-output/clawlancer-api.json"))
ENDPOINTS = {
    "info": "/api/info",
    "health": "/api/health",
    "stats": "/api/stats",
    "listings_bounty": "/api/listings?listing_type=BOUNTY",
    "listings_all": "/api/listings?limit=100",
    "docs": "/api-docs",
}
CREDENTIAL_RE = re.compile(r"\b(?:clw|claw|sk|pk|api)[_-](?:live[_-])?[A-Za-z0-9_-]{12,}", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            output[str(key)] = "[REDACTED]" if re.search(r"api.?key|secret|token|authorization|private", str(key), re.I) else sanitize(item)
        return output
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return CREDENTIAL_RE.sub("[REDACTED]", value)
    return value


def fetch(path: str) -> dict[str, Any]:
    url = BASE + path
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/html;q=0.8, */*;q=0.1",
            "User-Agent": "nexaworks-clawlancer-probe/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(5_000_000)
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                payload: Any = json.loads(raw.decode("utf-8")) if raw else None
            else:
                payload = raw.decode("utf-8", errors="replace")[:100_000]
            return {
                "ok": True,
                "status": response.status,
                "url": response.geturl(),
                "content_type": content_type,
                "payload": sanitize(payload),
            }
    except urllib.error.HTTPError as error:
        raw = error.read(100_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return {"ok": False, "status": error.code, "url": url, "payload": sanitize(payload)}
    except Exception as error:
        return {"ok": False, "url": url, "error": f"{type(error).__name__}: {error}"}


def unwrap_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("data", "items", "listings", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def main() -> int:
    evidence = {name: fetch(path) for name, path in ENDPOINTS.items()}
    listings_payload = evidence["listings_bounty"].get("payload")
    items = unwrap_items(listings_payload)
    compact = []
    for item in items:
        compact.append({
            key: sanitize(item.get(key))
            for key in (
                "id", "title", "description", "listing_type", "type", "category",
                "price", "price_wei", "priceWei", "bounty", "bounty_amount",
                "status", "seller_id", "agent_id", "created_at", "updated_at",
            )
            if item.get(key) is not None
        })
    result = {
        "generated_at": now_iso(),
        "base": BASE,
        "endpoints": evidence,
        "bounty_count": len(items),
        "bounties": compact[:100],
        "writes_performed": [],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "bounties": len(items)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())