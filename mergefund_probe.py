#!/usr/bin/env python3
"""Read-only MergeFund marketplace/API discovery.

The public marketplace currently renders bounty cards without exposing the
linked GitHub issue in parsed HTML. This probe downloads only public assets,
extracts candidate API routes and embedded bounty records, and tries a small
set of read-only endpoint conventions. It never authenticates or mutates data.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUT = Path(os.environ.get("MERGEFUND_OUTPUT_FILE", "market-output/mergefund.json"))
ORIGINS = ["https://app.mergefund.org", "https://dashboard.mergefund.org"]
HOME = ORIGINS[0] + "/"
USER_AGENT = "autonomous-income-runner-mergefund-probe/1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request(url: str, *, max_bytes: int = 5_000_000) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json,text/html,*/*", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read(max_bytes)
            text = raw.decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            try:
                parsed: Any = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return {
                "ok": True,
                "status": response.status,
                "url": response.geturl(),
                "content_type": content_type,
                "json": parsed,
                "text": None if parsed is not None else text,
                "bytes_read": len(raw),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(min(max_bytes, 500_000))
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        return {
            "ok": False,
            "status": exc.code,
            "url": url,
            "content_type": exc.headers.get("content-type", ""),
            "json": parsed,
            "text": None if parsed is not None else text[:20_000],
            "bytes_read": len(raw),
        }
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def absolute(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value))


def snippets(text: str, needles: list[str], radius: int = 500) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    lower = text.lower()
    seen: set[tuple[str, int]] = set()
    for needle in needles:
        start = 0
        target = needle.lower()
        while True:
            index = lower.find(target, start)
            if index < 0:
                break
            key = (target, index)
            if key not in seen:
                seen.add(key)
                found.append(
                    {
                        "needle": needle,
                        "snippet": text[max(0, index - radius) : index + len(needle) + radius],
                    }
                )
            start = index + len(target)
            if sum(1 for item in found if item["needle"] == needle) >= 5:
                break
    return found


def extract_urls(text: str) -> list[str]:
    patterns = [
        r"https?://[^\s\"'<>\\]+",
        r"[\"'](/api/[^\"']+)[\"']",
        r"[\"']([^\"']*(?:bount|market|project|issue)[^\"']*)[\"']",
    ]
    values: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(1) if match.lastindex else match.group(0)
            value = value.rstrip(")]},;`")
            if len(value) <= 500:
                values.add(value)
    return sorted(values)


def compact_response(response: dict[str, Any]) -> dict[str, Any]:
    compact = {key: response.get(key) for key in ("ok", "status", "url", "content_type", "bytes_read", "error") if response.get(key) is not None}
    if response.get("json") is not None:
        compact["json"] = response["json"]
    elif isinstance(response.get("text"), str):
        compact["text_preview"] = response["text"][:5000]
    return compact


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def main() -> int:
    home = request(HOME)
    home_text = home.get("text") if isinstance(home.get("text"), str) else ""
    script_urls = sorted(
        {
            absolute(HOME, match.group(1))
            for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", home_text, re.IGNORECASE)
        }
    )[:60]

    assets: list[dict[str, Any]] = []
    combined = home_text
    for url in script_urls:
        result = request(url)
        text = result.get("text") if isinstance(result.get("text"), str) else ""
        combined += "\n" + text
        assets.append(
            {
                "url": url,
                "ok": result.get("ok"),
                "status": result.get("status"),
                "bytes_read": result.get("bytes_read"),
                "interesting_snippets": snippets(
                    text,
                    [
                        "Gus Context Engine",
                        "Bonded",
                        "github.com",
                        "bounty",
                        "supabase",
                        "convex",
                        "graphql",
                        "/api/",
                    ],
                    radius=350,
                )[:30],
            }
        )

    endpoint_paths = [
        "/api/bounties",
        "/api/bounties?status=open",
        "/api/marketplace",
        "/api/marketplace/bounties",
        "/api/projects",
        "/api/public/bounties",
        "/api/v1/bounties",
        "/api/v1/marketplace",
        "/bounties.json",
    ]
    endpoint_results: dict[str, Any] = {}
    for origin in ORIGINS:
        for path in endpoint_paths:
            url = origin + path
            endpoint_results[url] = compact_response(request(url, max_bytes=2_000_000))

    report = {
        "generated_at": now_iso(),
        "home": compact_response(home),
        "script_urls": script_urls,
        "asset_analysis": assets,
        "combined_snippets": snippets(
            combined,
            [
                "Gus Context Engine",
                "Bonded",
                "gus.mergefund.org",
                "bondeduni.com",
                "github.com",
                "bountyId",
                "repositoryUrl",
                "issueNumber",
                "funded",
                "escrow",
            ],
            radius=1200,
        )[:80],
        "candidate_urls": extract_urls(combined)[:1000],
        "endpoint_results": endpoint_results,
    }
    atomic_write(OUTPUT, report)
    print(json.dumps({"ok": True, "output": str(OUTPUT), "scripts": len(script_urls)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
