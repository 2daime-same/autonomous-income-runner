#!/usr/bin/env python3
"""Read-only contract probe for Tetto and HYRVE agent marketplaces."""
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

OUTPUT = Path("market-output/tetto-hyrve-contract.json")
DOCS = Path("market-output/tetto-hyrve-docs.txt")
SITES = {
    "tetto": {
        "origins": ["https://tetto.io", "https://api.tetto.io"],
        "targets": [
            "https://tetto.io/",
            "https://tetto.io/skill.md",
            "https://tetto.io/docs",
            "https://tetto.io/openapi.json",
            "https://tetto.io/api/tasks",
            "https://tetto.io/api/agents",
            "https://tetto.io/marketplace",
            "https://api.tetto.io/openapi.json",
            "https://api.tetto.io/docs",
            "https://api.tetto.io/api/tasks",
            "https://api.tetto.io/api/agents",
        ],
    },
    "hyrve": {
        "origins": ["https://hyrveai.com", "https://api.hyrveai.com"],
        "targets": [
            "https://hyrveai.com/",
            "https://hyrveai.com/skill.md",
            "https://hyrveai.com/docs",
            "https://hyrveai.com/openapi.json",
            "https://hyrveai.com/marketplace",
            "https://hyrveai.com/api/tasks",
            "https://api.hyrveai.com/openapi.json",
            "https://api.hyrveai.com/docs",
            "https://api.hyrveai.com/api/tasks",
            "https://api.hyrveai.com/api/agents",
        ],
    },
}
USER_AGENT = "boundaryledger-agent-market-contract-probe/1.0"


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
        return {"ok": False, "status": exc.code, "url": url, "content_type": exc.headers.get("content-type", ""), "json": payload, "text": None if payload is not None else text[:20_000], "bytes": len(raw)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def absolute(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value))


def scripts(page_url: str, text: str, allowed_hosts: set[str]) -> list[str]:
    return sorted({
        absolute(page_url, match.group(1))
        for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, flags=re.I)
        if urllib.parse.urlparse(absolute(page_url, match.group(1))).netloc in allowed_hosts
    })[:80]


def routes(text: str, allowed_hosts: set[str], default_origin: str) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    patterns = [
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+((?:https?://[^\s`\"']+)|(?:/(?:api|v1|v2)/[^\s`\"']+))",
        r"[\"']((?:/api|/v1|/v2)/[A-Za-z0-9_?&=./{}:-]+)[\"']",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            if match.lastindex == 2:
                method, raw = match.group(1).upper(), match.group(2)
            else:
                method, raw = "UNKNOWN", match.group(1)
            url = raw if raw.startswith("http") else default_origin.rstrip("/") + raw
            parsed = urllib.parse.urlparse(url.rstrip(")]},;`"))
            if parsed.scheme == "https" and parsed.netloc in allowed_hosts:
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
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def main() -> int:
    report: dict[str, Any] = {"generated_at": now_iso(), "writes_performed": [], "markets": {}}
    docs_parts: list[str] = []
    for name, config in SITES.items():
        allowed = {urllib.parse.urlparse(origin).netloc for origin in config["origins"]}
        responses = {url: request(url) for url in config["targets"]}
        combined = "\n".join(result.get("text") or "" for result in responses.values())
        for url, result in responses.items():
            text = result.get("text") if isinstance(result.get("text"), str) else ""
            if text:
                docs_parts.append(f"\n\n===== {url} =====\n\n{text}")
        assets: dict[str, Any] = {}
        for page_url, result in responses.items():
            text = result.get("text") if isinstance(result.get("text"), str) else ""
            if not text:
                continue
            for script_url in scripts(page_url, text, allowed):
                if script_url in assets:
                    continue
                script_result = request(script_url)
                script_text = script_result.get("text") if isinstance(script_result.get("text"), str) else ""
                combined += "\n" + script_text
                if any(marker in script_text.lower() for marker in ("task", "job", "agent", "wallet", "escrow", "apply", "deliver", "submit", "/api/")):
                    assets[script_url] = {**compact(script_result), "routes": routes(script_text, allowed, config["origins"][0])[:250]}
        found_routes = routes(combined, allowed, config["origins"][0])
        get_results: dict[str, Any] = {}
        for route in found_routes:
            if route["method"] not in {"GET", "UNKNOWN"}:
                continue
            url = route["url"]
            if "{" in url or "}" in url or len(get_results) >= 120:
                continue
            get_results[url] = compact(request(url, 1_000_000))
        report["markets"][name] = {
            "origins": config["origins"],
            "responses": {url: compact(result) for url, result in responses.items()},
            "routes": found_routes,
            "safe_get_results": get_results,
            "assets": assets,
        }
    DOCS.parent.mkdir(parents=True, exist_ok=True)
    DOCS.write_text("".join(docs_parts) or "No marketplace docs available.\n", encoding="utf-8")
    atomic(OUTPUT, report)
    print(json.dumps({"ok": True, "markets": list(report["markets"]), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
