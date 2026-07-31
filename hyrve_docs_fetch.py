#!/usr/bin/env python3
"""Fetch HYRVE's official machine-readable API documentation."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Mapping

URL = "https://api.hyrveai.com/docs"
OUT_MD = Path("market-output/hyrve-api-docs.md")
OUT_JSON = Path("market-output/hyrve-api-docs-summary.json")


def longest_text(value: Any) -> str:
    candidates: list[str] = []
    def walk(item: Any) -> None:
        if isinstance(item, str):
            candidates.append(item)
        elif isinstance(item, Mapping):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return max(candidates, key=len, default="")


def main() -> int:
    request = urllib.request.Request(URL, headers={"Accept": "application/json", "User-Agent": "boundaryledger-hyrve-doc-fetch/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    markdown = longest_text(payload)
    if len(markdown) < 1000 or "self-register" not in markdown:
        raise RuntimeError("HYRVE docs response did not contain the expected machine documentation")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    summary = {
        "source": URL,
        "http_status": 200,
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, Mapping) else [],
        "documentation_bytes": len(markdown.encode("utf-8")),
        "contains_self_register": "self-register" in markdown,
        "contains_jobs": "/v1/jobs" in markdown,
        "contains_orders": "/v1/orders" in markdown,
        "contains_wallet": "/v1/wallet" in markdown,
        "writes_performed": [],
        "authentication_used": False,
    }
    temporary = OUT_JSON.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, OUT_JSON)
    print(json.dumps({"ok": True, "documentation_bytes": summary["documentation_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
