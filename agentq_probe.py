#!/usr/bin/env python3
"""Read-only discovery of AgentQ's registration, task, delivery and payout contract.

Only public GET requests are made. The probe never registers, comments, claims,
submits work, changes wallet state, or sends credentials. Output is compact and
redacts credential-like material before it can be committed.
"""
from __future__ import annotations

import hashlib
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

ORIGIN = "https://agentq.tech"
OUTPUT = Path(os.environ.get("AGENTQ_OUTPUT", "market-output/agentq-contract.json"))
USER_AGENT = "autonomous-income-runner-agentq-probe/1.0"
MAX_BYTES = 4_000_000
START_URLS = [
    f"{ORIGIN}/",
    f"{ORIGIN}/api/v1/docs",
    f"{ORIGIN}/register",
    f"{ORIGIN}/post/270001",
    f"{ORIGIN}/post/260001",
    f"{ORIGIN}/post/250001",
]
NEEDLES = [
    "agentRegister",
    "apiKey",
    "wallet",
    "withdraw",
    "payout",
    "bounty",
    "reward",
    "claim",
    "apply",
    "submit",
    "deliver",
    "complete",
    "approve",
    "posts.create",
    "comments.create",
    "/api/trpc/",
    "/api/v1/",
    "stripe",
    "paypal",
]
SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|bearer|secret|token|private[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9._~+/=-]{12,})"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact(text: str) -> str:
    return SECRET_PATTERN.sub(lambda match: match.group(0).replace(match.group(1), "[REDACTED]"), text)


def request(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/markdown,text/html,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read(MAX_BYTES)
            text = redact(raw.decode("utf-8", errors="replace"))
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
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "json": parsed,
                "text": None if parsed is not None else text,
            }
    except urllib.error.HTTPError as error:
        raw = error.read(min(MAX_BYTES, 500_000))
        text = redact(raw.decode("utf-8", errors="replace"))
        return {
            "ok": False,
            "status": error.code,
            "url": url,
            "content_type": error.headers.get("content-type", ""),
            "bytes": len(raw),
            "text": text,
        }
    except Exception as error:
        return {"ok": False, "url": url, "error": f"{type(error).__name__}: {error}"}


def script_urls(base_url: str, text: str) -> list[str]:
    urls = {
        urllib.parse.urljoin(base_url, html.unescape(match.group(1)))
        for match in re.finditer(r"<script[^>]+src=['\"]([^'\"]+)['\"]", text, re.I)
    }
    return sorted(
        url for url in urls
        if urllib.parse.urlparse(url).scheme == "https"
        and urllib.parse.urlparse(url).netloc == "agentq.tech"
    )[:80]


def contexts(text: str, radius: int = 420, per_needle: int = 5) -> list[dict[str, str]]:
    lower = text.lower()
    output: list[dict[str, str]] = []
    for needle in NEEDLES:
        target = needle.lower()
        start = 0
        count = 0
        while count < per_needle:
            index = lower.find(target, start)
            if index < 0:
                break
            output.append({
                "needle": needle,
                "context": text[max(0, index - radius): index + len(needle) + radius],
            })
            count += 1
            start = index + len(target)
    return output[:160]


def urls(text: str) -> list[str]:
    found: set[str] = set()
    patterns = [
        r"https?://[^\s'\"<>\\]+",
        r"['\"](/api/(?:trpc|v1)/[^'\"]*)['\"]",
        r"['\"]([A-Za-z0-9_.-]+\.(?:create|claim|apply|submit|deliver|complete|approve|withdraw|balance|register))['\"]",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = match.group(1) if match.lastindex else match.group(0)
            value = html.unescape(value).rstrip(")]},;`'\"")
            if len(value) <= 700:
                found.add(value)
    return sorted(found)[:1000]


def compact(response: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: response.get(key)
        for key in ("ok", "status", "url", "content_type", "bytes", "sha256", "error")
        if response.get(key) is not None
    }
    if response.get("json") is not None:
        value = response["json"]
        result["json"] = value if len(json.dumps(value, ensure_ascii=False)) <= 250_000 else str(value)[:250_000]
    elif isinstance(response.get("text"), str):
        text = response["text"]
        result["text_preview"] = text[:20_000]
        result["contexts"] = contexts(text)
        result["candidate_urls"] = urls(text)
    return result


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    pages: dict[str, Any] = {}
    scripts: dict[str, Any] = {}
    discovered_scripts: set[str] = set()
    combined = ""

    for url in START_URLS:
        response = request(url)
        pages[url] = compact(response)
        text = response.get("text") if isinstance(response.get("text"), str) else ""
        combined += "\n" + text
        discovered_scripts.update(script_urls(response.get("url") or url, text))

    for url in sorted(discovered_scripts)[:80]:
        response = request(url)
        text = response.get("text") if isinstance(response.get("text"), str) else ""
        combined += "\n" + text
        found_contexts = contexts(text)
        found_urls = urls(text)
        if found_contexts or found_urls:
            scripts[url] = {
                "ok": response.get("ok"),
                "status": response.get("status"),
                "bytes": response.get("bytes"),
                "sha256": response.get("sha256"),
                "contexts": found_contexts,
                "candidate_urls": found_urls,
            }

    report = {
        "generated_at": now_iso(),
        "writes_performed": [],
        "safety": "public GET requests only; no registration, claim, comment, delivery, wallet or payment mutation",
        "pages": pages,
        "script_count": len(discovered_scripts),
        "relevant_scripts": scripts,
        "combined_candidate_urls": urls(combined),
        "combined_contexts": contexts(combined, radius=700, per_needle=12),
    }
    atomic_write(OUTPUT, report)
    print(json.dumps({"ok": True, "output": str(OUTPUT), "scripts": len(discovered_scripts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
