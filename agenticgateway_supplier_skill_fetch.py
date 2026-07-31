#!/usr/bin/env python3
"""Fetch and parse the official Agentic Gateway supplier skill."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URL = "https://api.agenticgateway.io/v1/supplier-skill.md"
SKILL = Path("market-output/agenticgateway-supplier-skill.md")
SUMMARY = Path("market-output/agenticgateway-supplier-contract.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch() -> str:
    request = urllib.request.Request(
        URL,
        headers={
            "Accept": "text/markdown,text/plain,*/*",
            "User-Agent": "boundaryledger-agenticgateway-supplier-fetch/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            return response.read(2_000_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {error.code}: {body}") from error


def routes(text: str) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    for match in re.finditer(
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+((?:https?://[^\s`\"']+)|(?:/v1/[^\s`\"']+)|(?:/api/[^\s`\"']+))",
        text,
        flags=re.I,
    ):
        method = match.group(1).upper()
        path = match.group(2).rstrip(")]},;`")
        if path.startswith("/"):
            path = "https://api.agenticgateway.io" + path
        found[(method, path)] = {"method": method, "url": path}
    for match in re.finditer(r"[\"']((?:/v1|/api)/[A-Za-z0-9_?&=./{}:-]+)[\"']", text):
        path = "https://api.agenticgateway.io" + match.group(1)
        found.setdefault(("UNKNOWN", path), {"method": "UNKNOWN", "url": path})
    return sorted(found.values(), key=lambda item: (item["url"], item["method"]))


def headings(text: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"^#{1,4}\s+(.+)$", text, flags=re.M)]


def keywords(text: str) -> dict[str, bool]:
    lower = text.lower()
    return {
        name: token in lower
        for name, token in {
            "registration": "register",
            "approval": "approv",
            "wallet": "wallet",
            "settlement": "settlement",
            "webhook": "webhook",
            "tool_submission": "tool submission",
            "api_submission": "api submission",
            "ui_only": "via ui",
            "api_key": "api key",
            "signature": "signature",
            "email": "email",
        }.items()
    }


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    text = fetch()
    SKILL.parent.mkdir(parents=True, exist_ok=True)
    SKILL.write_text(text, encoding="utf-8")
    summary = {
        "generated_at": now_iso(),
        "source": URL,
        "writes_performed": [],
        "bytes": len(text.encode("utf-8")),
        "headings": headings(text),
        "routes": routes(text),
        "keywords": keywords(text),
    }
    atomic_json(SUMMARY, summary)
    print(json.dumps({"ok": True, "routes": len(summary["routes"]), "bytes": summary["bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
