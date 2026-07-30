#!/usr/bin/env python3
"""Extract public MergeFund frontend routes and bounty card contracts, read-only."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = "https://app.mergefund.org/"
OUTPUT = Path("market-output/mergefund-frontend-contract.json")
UA = "nexaworks-mergefund-contract/1.0"

SECRET_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"https://[a-z0-9-]+\.supabase\.co", re.I),
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get(url: str, limit: int = 8_000_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/javascript,*/*"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read(limit).decode("utf-8", errors="replace")


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_PUBLIC_CLIENT_CREDENTIAL]", text)
    return text


def contexts(text: str, needles: list[str], radius: int = 1800, cap: int = 8) -> list[dict[str, str]]:
    lower = text.lower()
    rows = []
    for needle in needles:
        position = 0
        hits = 0
        while hits < cap:
            index = lower.find(needle.lower(), position)
            if index < 0:
                break
            rows.append({
                "needle": needle,
                "context": redact(text[max(0, index - radius):index + len(needle) + radius]),
            })
            position = index + len(needle)
            hits += 1
    return rows


def main() -> int:
    page = get(HOME)
    scripts = sorted({
        urllib.parse.urljoin(HOME, html.unescape(match.group(1)))
        for match in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', page, flags=re.I)
    })
    assets: list[dict[str, Any]] = []
    combined = page
    for url in scripts:
        try:
            text = get(url)
        except Exception as error:
            assets.append({"url": url, "ok": False, "error": f"{type(error).__name__}: {error}"})
            continue
        combined += "\n" + text
        relevant = any(marker in text for marker in ("Gus Context Engine", "Bonded", "/api/bounties", "gus-apply", "bonded-apply"))
        assets.append({
            "url": url,
            "ok": True,
            "bytes": len(text.encode()),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "relevant": relevant,
        })

    fetch_calls = sorted(set(re.findall(r'fetch\((?:"|\')([^"\']+)', combined)))
    route_strings = sorted(set(re.findall(r'["\'](/api/[A-Za-z0-9_?&=/.-]+)["\']', combined)))
    github_urls = sorted(set(re.findall(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/(?:issues|pull)/\d+)?', combined)))
    supabase_tables = sorted(set(re.findall(r'\.from\(["\']([^"\']+)["\']\)', combined)))
    storage_keys = sorted(set(re.findall(r'mergefund:[A-Za-z0-9:_-]+', combined)))

    report = {
        "generated_at": now(),
        "home": HOME,
        "script_count": len(scripts),
        "assets": assets,
        "fetch_calls": fetch_calls,
        "api_routes": route_strings,
        "github_urls": github_urls,
        "supabase_table_names": supabase_tables,
        "local_storage_keys": storage_keys,
        "contexts": contexts(combined, [
            "gus-apply",
            "bonded-apply",
            "Gus Context Engine",
            "Bonded",
            "/api/bounties",
            "/api/stats",
            "Sign In to Apply",
            "Used your profile to apply",
            "issue_id",
            "repository_full_name",
            "repo_full_name",
            "github_url",
            "apply",
        ], radius=2200, cap=5),
        "writes_performed": [],
        "credential_values_recorded": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "routes": len(route_strings), "github_urls": len(github_urls), "tables": len(supabase_tables)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
