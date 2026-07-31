#!/usr/bin/env python3
"""Read-only Agentic Gateway supplier and marketplace contract probe."""
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

ORIGINS = ["https://api.agenticgateway.io", "https://agenticgateway.io"]
OUTPUT = Path("market-output/agenticgateway-contract.json")
SKILL_COPY = Path("market-output/agenticgateway-skill.md")
USER_AGENT = "boundaryledger-agenticgateway-probe/1.0"


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
    allowed = {urllib.parse.urlparse(value).netloc for value in ORIGINS}
    found = {
        absolute(page_url, match.group(1))
        for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, flags=re.I)
    }
    return sorted(url for url in found if urllib.parse.urlparse(url).netloc in allowed)[:60]


def routes(text: str) -> list[dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    patterns = [
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+((?:https?://[^\s`\"']+)|(?:/v1/[^\s`\"']+)|(?:/api/[^\s`\"']+))",
        r"[\"']((?:/v1|/api)/[A-Za-z0-9_?&=./{}:-]+)[\"']",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            if match.lastindex == 2:
                method = match.group(1).upper()
                raw = match.group(2)
            else:
                method = "UNKNOWN"
                raw = match.group(1)
            url = raw if raw.startswith("http") else "https://api.agenticgateway.io" + raw
            parsed = urllib.parse.urlparse(url.rstrip(")]},;`"))
            if parsed.scheme == "https" and parsed.netloc in {"api.agenticgateway.io", "agenticgateway.io"}:
                clean = urllib.parse.urlunparse(parsed)
                result[(method, clean)] = {"method": method, "url": clean}
    return sorted(result.values(), key=lambda item: (item["url"], item["method"]))


def compact(value: dict[str, Any]) -> dict[str, Any]:
    out = {key: value.get(key) for key in ("ok", "status", "url", "content_type", "bytes", "error") if value.get(key) is not None}
    if value.get("json") is not None:
        payload = value["json"]
        if isinstance(payload, dict):
            out["json_keys"] = list(payload)[:100]
            out["json_preview"] = payload
        elif isinstance(payload, list):
            out["json_count"] = len(payload)
            out["json_preview"] = payload[:30]
    elif isinstance(value.get("text"), str):
        out["text_preview"] = value["text"][:5000]
    return out


def atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def main() -> int:
    targets = [
        "https://api.agenticgateway.io/v1/skill.md",
        "https://api.agenticgateway.io/v1/tools",
        "https://api.agenticgateway.io/v1/tools/search?query=validation",
        "https://agenticgateway.io/",
        "https://agenticgateway.io/docs",
        "https://agenticgateway.io/suppliers",
        "https://agenticgateway.io/marketplace",
    ]
    responses = {url: request(url) for url in targets}
    combined = "\n".join(value.get("text") or "" for value in responses.values())
    asset_results: dict[str, Any] = {}
    for page_url, value in list(responses.items()):
        text = value.get("text") if isinstance(value.get("text"), str) else ""
        if not text:
            continue
        for script_url in scripts(page_url, text):
            if script_url in asset_results:
                continue
            result = request(script_url)
            script_text = result.get("text") if isinstance(result.get("text"), str) else ""
            combined += "\n" + script_text
            if any(marker in script_text.lower() for marker in ("supplier", "provider", "listing", "wallet", "/v1/", "/api/")):
                asset_results[script_url] = {**compact(result), "routes": routes(script_text)[:200]}

    found_routes = routes(combined)
    get_results: dict[str, Any] = {}
    for route in found_routes:
        if route["method"] not in {"GET", "UNKNOWN"}:
            continue
        url = route["url"]
        if "{" in url or "}" in url or len(get_results) >= 100:
            continue
        get_results[url] = compact(request(url, 1_000_000))

    skill_text = responses[targets[0]].get("text") if isinstance(responses[targets[0]].get("text"), str) else ""
    SKILL_COPY.parent.mkdir(parents=True, exist_ok=True)
    SKILL_COPY.write_text(skill_text or "Agentic Gateway skill.md unavailable.\n", encoding="utf-8")
    report = {
        "generated_at": now_iso(),
        "writes_performed": [],
        "responses": {key: compact(value) for key, value in responses.items()},
        "routes": found_routes,
        "safe_get_results": get_results,
        "assets": asset_results,
    }
    atomic(OUTPUT, report)
    print(json.dumps({"ok": True, "routes": len(found_routes), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
