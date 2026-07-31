#!/usr/bin/env python3
"""Read-only AIGEN open bounty protocol probe."""
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
from typing import Any, Mapping

ORIGIN = "https://cryptogenesis.duckdns.org"
OUTPUT = Path("market-output/aigen-contract.json")
DOCS_COPY = Path("market-output/aigen-docs.txt")
USER_AGENT = "boundaryledger-aigen-probe/1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request(url: str, max_bytes: int = 4_000_000) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json,text/markdown,text/html,*/*", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read(max_bytes)
            text = raw.decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            return {"ok": True, "status": response.status, "url": response.geturl(), "content_type": response.headers.get("content-type", ""), "json": payload, "text": None if payload is not None else text, "bytes": len(raw)}
    except urllib.error.HTTPError as exc:
        raw = exc.read(500_000)
        text = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        return {"ok": False, "status": exc.code, "url": url, "json": payload, "text": None if payload is not None else text[:20_000], "bytes": len(raw)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def absolute(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value))


def scripts(page_url: str, text: str) -> list[str]:
    host = urllib.parse.urlparse(ORIGIN).netloc
    return sorted({
        absolute(page_url, match.group(1))
        for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, flags=re.I)
        if urllib.parse.urlparse(absolute(page_url, match.group(1))).netloc == host
    })[:60]


def routes(text: str) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    patterns = [
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+((?:https?://[^\s`\"']+)|(?:/[A-Za-z0-9_?&=./{}:-]+))",
        r"[\"']((?:/work|/missions|/api)/[A-Za-z0-9_?&=./{}:-]*)[\"']",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            if match.lastindex == 2:
                method, raw = match.group(1).upper(), match.group(2)
            else:
                method, raw = "UNKNOWN", match.group(1)
            url = raw if raw.startswith("http") else ORIGIN + raw
            parsed = urllib.parse.urlparse(url.rstrip(")]},;`"))
            if parsed.scheme == "https" and parsed.netloc == urllib.parse.urlparse(ORIGIN).netloc:
                clean = urllib.parse.urlunparse(parsed)
                found[(method, clean)] = {"method": method, "url": clean}
    return sorted(found.values(), key=lambda item: (item["url"], item["method"]))


def compact(value: dict[str, Any]) -> dict[str, Any]:
    out = {key: value.get(key) for key in ("ok", "status", "url", "content_type", "bytes", "error") if value.get(key) is not None}
    if value.get("json") is not None:
        payload = value["json"]
        if isinstance(payload, Mapping):
            out["json_keys"] = list(payload)[:100]
            out["json_preview"] = payload
        elif isinstance(payload, list):
            out["json_count"] = len(payload)
            out["json_preview"] = payload[:50]
    elif isinstance(value.get("text"), str):
        out["text_preview"] = value["text"][:5000]
    return out


def atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    targets = [
        ORIGIN + "/",
        ORIGIN + "/skill.md",
        ORIGIN + "/docs",
        ORIGIN + "/openapi.json",
        ORIGIN + "/work/board",
        ORIGIN + "/missions",
        ORIGIN + "/api/missions",
    ]
    responses = {url: request(url) for url in targets}
    combined = "\n".join(result.get("text") or "" for result in responses.values())
    assets: dict[str, Any] = {}
    for page_url, result in responses.items():
        text = result.get("text") if isinstance(result.get("text"), str) else ""
        if not text:
            continue
        for script_url in scripts(page_url, text):
            if script_url in assets:
                continue
            script_result = request(script_url)
            script_text = script_result.get("text") if isinstance(script_result.get("text"), str) else ""
            combined += "\n" + script_text
            if any(marker in script_text.lower() for marker in ("mission", "submit", "wallet", "escrow", "/work/")):
                assets[script_url] = {**compact(script_result), "routes": routes(script_text)[:200]}

    found_routes = routes(combined)
    get_results: dict[str, Any] = {}
    for route in found_routes:
        if route["method"] not in {"GET", "UNKNOWN"}:
            continue
        url = route["url"]
        if "{" in url or "}" in url or len(get_results) >= 100:
            continue
        get_results[url] = compact(request(url, 1_000_000))

    docs_text = "\n\n".join(result.get("text") or "" for result in responses.values() if isinstance(result.get("text"), str))
    DOCS_COPY.parent.mkdir(parents=True, exist_ok=True)
    DOCS_COPY.write_text(docs_text or "AIGEN documentation unavailable.\n", encoding="utf-8")
    report = {
        "generated_at": now_iso(),
        "writes_performed": [],
        "responses": {url: compact(result) for url, result in responses.items()},
        "routes": found_routes,
        "safe_get_results": get_results,
        "assets": assets,
    }
    atomic(OUTPUT, report)
    print(json.dumps({"ok": True, "routes": len(found_routes), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
