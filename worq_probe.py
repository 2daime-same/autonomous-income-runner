#!/usr/bin/env python3
"""Read-only probe of WORQ public job and settlement evidence."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path(os.environ.get("WORQ_OUTPUT", "worq-output/live.json"))
URLS = {
    "jobs_open": "https://api.worq.dev/v1/jobs?status=open&limit=100",
    "jobs_bidding": "https://api.worq.dev/v1/jobs?status=bidding&limit=100",
    "stats": "https://api.worq.dev/v1/spectator/stats",
    "feed": "https://api.worq.dev/v1/spectator/feed?limit=100",
    "agents": "https://api.worq.dev/v1/agents?limit=100&sort=earned",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "nexaworks-worq-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read(4_000_000).decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw[:20_000]
            return {"ok": True, "status": response.status, "url": response.geturl(), "payload": payload}
    except urllib.error.HTTPError as error:
        raw = error.read(20_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return {"ok": False, "status": error.code, "url": url, "payload": payload}
    except Exception as error:
        return {"ok": False, "url": url, "error": f"{type(error).__name__}: {error}"}


def unwrap(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "jobs", "items", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
    return []


def main() -> int:
    endpoints = {name: fetch(url) for name, url in URLS.items()}
    jobs = []
    for source in ("jobs_open", "jobs_bidding"):
        for item in unwrap(endpoints[source].get("payload")):
            jobs.append({
                "source": source,
                "id": item.get("id"),
                "title": item.get("title"),
                "description": item.get("description"),
                "status": item.get("status"),
                "budget_usdc": item.get("budget_usdc") or item.get("budgetUsdc") or item.get("budget"),
                "deadline": item.get("deadline") or item.get("deadline_at"),
                "tags": item.get("tags"),
                "created_at": item.get("created_at"),
                "escrow": item.get("escrow") or item.get("escrow_status"),
                "poster": item.get("poster") or item.get("poster_agent"),
            })
    result = {"generated_at": now_iso(), "endpoints": endpoints, "job_count": len(jobs), "jobs": jobs}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "jobs": len(jobs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
