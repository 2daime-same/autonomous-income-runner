#!/usr/bin/env python3
"""Read-only probe for MergeFund's public bounty pagination/filter contract."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://app.mergefund.org/api/bounties"
OUTPUT = Path("market-output/mergefund-query-variants.json")

QUERIES = [
    {},
    {"page": 1, "limit": 1},
    {"page": 1, "limit": 2},
    {"page": 1, "limit": 50},
    {"page": 0, "limit": 50},
    {"offset": 0, "limit": 50},
    {"status": "funded"},
    {"status": "funded", "page": 1, "limit": 50},
    {"status": "all", "page": 1, "limit": 50},
    {"status": "open,funded", "page": 1, "limit": 50},
    {"sort": "newest", "page": 1, "limit": 50},
    {"sort": "oldest", "page": 1, "limit": 50},
    {"sort": "reward_desc", "page": 1, "limit": 50},
    {"search": "Gus"},
    {"search": "Bonded"},
    {"q": "Gus"},
    {"query": "Gus"},
    {"funded": "true"},
    {"isFunded": "true"},
    {"include": "funded"},
    {"includeClosed": "true"},
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get(query: dict[str, Any]) -> dict[str, Any]:
    url = BASE
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "nexaworks-mergefund-query-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"text_preview": raw[:2000]}
            return {"ok": True, "status": response.status, "url": response.geturl(), "payload": payload}
    except urllib.error.HTTPError as error:
        raw = error.read(100_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"text_preview": raw[:2000]}
        return {"ok": False, "status": error.code, "url": url, "payload": payload}
    except Exception as error:
        return {"ok": False, "url": url, "error": f"{type(error).__name__}: {error}"}


def main() -> int:
    rows = []
    for query in QUERIES:
        result = get(query)
        payload = result.get("payload")
        if isinstance(payload, dict):
            bounties = payload.get("bounties")
            result["summary"] = {
                "total": payload.get("total"),
                "page": payload.get("page"),
                "limit": payload.get("limit"),
                "bounty_count": len(bounties) if isinstance(bounties, list) else None,
                "titles": [str(item.get("title")) for item in bounties if isinstance(item, dict)][:10] if isinstance(bounties, list) else [],
            }
        rows.append({"query": query, "result": result})
    report = {"generated_at": now(), "base": BASE, "writes_performed": [], "results": rows}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "queries": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
