#!/usr/bin/env python3
"""Read-only primary-source probe for current Molt-family paid-work markets.

Only GET requests are issued. The probe captures status, content type, bounded
response bodies, and compact inventory counts so empty/demo markets can be
rejected before any human registration step is requested.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path(os.environ.get("MOLT_MARKET_OUTPUT", "market-output/molt-markets.json"))
TIMEOUT = 45
MAX_BYTES = 2_000_000
USER_AGENT = "nexaworks-autonomous-income-molt-probe/1.0"

ENDPOINTS = {
    "moltbotmarket_jobs": "https://moltbotmarket.com/api/v1/jobs?status=open",
    "moltbotmarket_jobs_www": "https://www.moltbotmarket.com/api/v1/jobs?status=open",
    "moltbotmarket_docs": "https://www.moltbotmarket.com/docs",
    "molt_jobs_skill": "https://molt-jobs.com/skill.md",
    "molt_jobs_jobs_v1": "https://molt-jobs.com/api/v1/jobs?status=open",
    "molt_jobs_jobs": "https://molt-jobs.com/api/jobs?status=open",
    "molt_jobs_page": "https://molt-jobs.com/jobs",
    "moltjobs_io_skill": "https://moltjobs.io/skill.md",
    "moltjobs_io_jobs": "https://api.moltjobs.io/v1/jobs?status=OPEN",
    "moltjobs_io_stats": "https://api.moltjobs.io/v1/stats",
    "moltask_onboard": "https://moltask.com/api/onboard",
    "moltask_bounties": "https://moltask.com/api/bounties",
    "moltask_asks": "https://moltask.com/api/asks?status=open",
    "moltask_docs": "https://moltask.com/docs",
    "moltcities_jobs": "https://moltcities.org/api/jobs?status=open",
    "moltcities_skill": "https://moltcities.org/skill",
}

SECRET_PATTERNS = [
    re.compile(r"\b(?:mj|mk|cph|sk)_(?:live|test)?_?[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._-]+"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", text)
    return text


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/markdown,text/plain,text/html,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES)
            status = response.status
            final_url = response.geturl()
            content_type = response.headers.get("content-type", "")
    except urllib.error.HTTPError as error:
        raw = error.read(min(MAX_BYTES, 500_000))
        status = error.code
        final_url = url
        content_type = error.headers.get("content-type", "")
    except Exception as error:
        return {"ok": False, "url": url, "error": f"{type(error).__name__}: {error}"}

    text = redact(raw.decode("utf-8", errors="replace"))
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    return {
        "ok": 200 <= status < 400,
        "status": status,
        "url": url,
        "final_url": final_url,
        "content_type": content_type,
        "bytes_read": len(raw),
        "json": parsed,
        "text": None if parsed is not None else text[:80_000],
    }


def unwrap_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        for key in ("jobs", "bounties", "asks", "items", "data", "results", "open_jobs"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
    return []


def compact_items(value: Any) -> dict[str, Any]:
    items = unwrap_items(value)
    compact = []
    for raw in items[:100]:
        if not isinstance(raw, Mapping):
            continue
        compact.append(
            {
                key: raw.get(key)
                for key in (
                    "id",
                    "slug",
                    "title",
                    "name",
                    "description",
                    "status",
                    "state",
                    "budget",
                    "budget_usd",
                    "pay_usdc",
                    "reward",
                    "reward_amount",
                    "bounty",
                    "deadline",
                    "created_at",
                    "skills",
                    "category",
                    "acceptance_criteria",
                    "url",
                )
                if raw.get(key) is not None
            }
        )
    scalar = {}
    if isinstance(value, Mapping):
        for key in (
            "total",
            "count",
            "page",
            "fee",
            "platform_fee",
            "registration_fee",
            "min_payout",
            "currency",
            "message",
            "error",
        ):
            if key in value:
                scalar[key] = value.get(key)
    return {"item_count": len(items), "items": compact, "scalar": scalar}


def text_signals(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    lower = text.lower()
    keys = {
        "registration_mentions": ["register", "api key", "sign in", "signup", "no signup"],
        "fee_mentions": ["fee", "free", "credit card", "deposit", "bond"],
        "payment_mentions": ["usdc", "stripe", "bank", "escrow", "wallet", "payout"],
        "inventory_mentions": ["open jobs", "bounties", "jobs", "live"],
    }
    return {
        category: [needle for needle in needles if needle in lower]
        for category, needles in keys.items()
    }


def main() -> int:
    report: dict[str, Any] = {"generated_at": now_iso(), "endpoints": {}}
    for name, url in ENDPOINTS.items():
        result = fetch(url)
        entry = {
            key: result.get(key)
            for key in ("ok", "status", "url", "final_url", "content_type", "bytes_read", "error")
            if result.get(key) is not None
        }
        if result.get("json") is not None:
            entry["inventory"] = compact_items(result["json"])
            entry["json_preview"] = result["json"]
        else:
            text = result.get("text") if isinstance(result.get("text"), str) else None
            entry["signals"] = text_signals(text)
            entry["text_preview"] = text[:20_000] if text else None
        report["endpoints"][name] = entry

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "endpoints": len(ENDPOINTS), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
