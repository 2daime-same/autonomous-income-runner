#!/usr/bin/env python3
"""Read-only AgentMart onboarding/API contract probe."""
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

ORIGIN = "https://agentmart.store"
OUTPUT = Path("market-output/agentmart-contract.json")
SKILL_COPY = Path("market-output/agentmart-skill.md")
USER_AGENT = "boundaryledger-agentmart-probe/1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request(url: str, *, max_bytes: int = 4_000_000) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/markdown,text/html,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read(max_bytes)
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return {
                "ok": True,
                "status": response.status,
                "url": response.geturl(),
                "content_type": response.headers.get("content-type", ""),
                "text": text if parsed is None else None,
                "json": parsed,
                "bytes": len(raw),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(500_000)
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
            "text": text[:20_000] if parsed is None else None,
            "json": parsed,
            "bytes": len(raw),
        }
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def absolute(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value))


def extract_routes(text: str) -> list[dict[str, str]]:
    routes: dict[tuple[str, str], dict[str, str]] = {}
    patterns = [
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+((?:https?://[^\s`\"']+)|(?:/api/[^\s`\"']+))",
        r"curl\s+(?:-[A-Z]\s+)?(GET|POST|PUT|PATCH|DELETE)?[^\n]*?(https?://[^\s`\"'\\]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            method = (match.group(1) or "GET").upper()
            path = match.group(2).rstrip(")]},;`")
            if path.startswith("/"):
                path = ORIGIN + path
            parsed = urllib.parse.urlparse(path)
            if parsed.scheme != "https" or parsed.netloc != "agentmart.store":
                continue
            routes[(method, path)] = {"method": method, "url": path}
    for match in re.finditer(r"[\"'](/api/[A-Za-z0-9_?&=./{}:-]+)[\"']", text):
        path = ORIGIN + match.group(1)
        routes.setdefault(("UNKNOWN", path), {"method": "UNKNOWN", "url": path})
    return sorted(routes.values(), key=lambda item: (item["url"], item["method"]))


def extract_scripts(page_url: str, text: str) -> list[str]:
    return sorted({
        absolute(page_url, match.group(1))
        for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, flags=re.I)
        if urllib.parse.urlparse(absolute(page_url, match.group(1))).netloc == "agentmart.store"
    })[:50]


def compact(result: dict[str, Any]) -> dict[str, Any]:
    value = {key: result.get(key) for key in ("ok", "status", "url", "content_type", "bytes", "error") if result.get(key) is not None}
    if result.get("json") is not None:
        payload = result["json"]
        if isinstance(payload, dict):
            value["json_keys"] = list(payload)[:100]
            value["json_preview"] = payload
        elif isinstance(payload, list):
            value["json_count"] = len(payload)
            value["json_preview"] = payload[:20]
    elif isinstance(result.get("text"), str):
        value["text_preview"] = result["text"][:5000]
    return value


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
    skill = request(ORIGIN + "/skill.md")
    home = request(ORIGIN + "/")
    seller = request(ORIGIN + "/seller")
    dashboard = request(ORIGIN + "/seller/dashboard")
    skill_text = skill.get("text") if isinstance(skill.get("text"), str) else ""
    home_text = home.get("text") if isinstance(home.get("text"), str) else ""
    seller_text = seller.get("text") if isinstance(seller.get("text"), str) else ""
    dashboard_text = dashboard.get("text") if isinstance(dashboard.get("text"), str) else ""

    scripts: dict[str, Any] = {}
    combined = "\n".join((skill_text, home_text, seller_text, dashboard_text))
    for page_url, text in ((ORIGIN + "/", home_text), (ORIGIN + "/seller", seller_text), (ORIGIN + "/seller/dashboard", dashboard_text)):
        for script_url in extract_scripts(page_url, text):
            if script_url in scripts:
                continue
            result = request(script_url)
            script_text = result.get("text") if isinstance(result.get("text"), str) else ""
            combined += "\n" + script_text
            if "/api/" in script_text or any(word in script_text.lower() for word in ("register", "product", "shop", "seller", "wallet")):
                scripts[script_url] = {
                    **compact(result),
                    "routes": extract_routes(script_text)[:200],
                }

    routes = extract_routes(combined)
    safe_get_results: dict[str, Any] = {}
    for route in routes:
        if route["method"] not in {"GET", "UNKNOWN"}:
            continue
        url = route["url"]
        if "{" in url or "}" in url or len(safe_get_results) >= 80:
            continue
        safe_get_results[url] = compact(request(url, max_bytes=1_000_000))

    SKILL_COPY.parent.mkdir(parents=True, exist_ok=True)
    SKILL_COPY.write_text(skill_text or "AgentMart skill.md was unavailable.\n", encoding="utf-8")
    report = {
        "generated_at": now_iso(),
        "writes_performed": [],
        "skill": compact(skill),
        "home": compact(home),
        "seller": compact(seller),
        "dashboard": compact(dashboard),
        "routes": routes,
        "safe_get_results": safe_get_results,
        "scripts": scripts,
    }
    atomic_write(OUTPUT, report)
    print(json.dumps({"ok": True, "routes": len(routes), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
