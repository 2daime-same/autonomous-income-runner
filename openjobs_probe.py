#!/usr/bin/env python3
"""Read-only OpenJobs production inventory and API-contract probe."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path(os.environ.get("OPENJOBS_OUTPUT", "openjobs-output/live.json"))
URLS = {
    "skill": "https://openjobs.bot/skill.md",
    "jobs_default": "https://openjobs.bot/api/jobs?limit=100",
    "jobs_open_lower": "https://openjobs.bot/api/jobs?status=open&limit=100",
    "jobs_open_upper": "https://openjobs.bot/api/jobs?status=OPEN&limit=100",
    "stats": "https://openjobs.bot/api/stats",
    "health": "https://openjobs.bot/api/health",
    "payouts": "https://openjobs.bot/api/payouts?limit=100",
}
TIMEOUT = 45


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json,text/markdown,text/plain", "User-Agent": "nexaworks-openjobs-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(5_000_000).decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            try:
                payload: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = None
            result: dict[str, Any] = {
                "ok": True,
                "status": response.status,
                "url": response.geturl(),
                "content_type": content_type,
                "bytes": len(raw.encode("utf-8")),
            }
            if payload is not None:
                result["payload"] = payload
            else:
                result["text_preview"] = raw[:100_000]
            return result
    except urllib.error.HTTPError as error:
        raw = error.read(30_000).decode("utf-8", errors="replace")
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
            if isinstance(candidate, Mapping):
                for nested in ("jobs", "items", "results"):
                    nested_value = candidate.get(nested)
                    if isinstance(nested_value, list):
                        return [item for item in nested_value if isinstance(item, Mapping)]
    return []


def compact_job(item: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "id", "title", "description", "status", "type", "jobType", "reward", "rewardAmount",
        "rewardToken", "currency", "budget", "skills", "requirements", "acceptanceCriteria",
        "deadline", "deadlineAt", "createdAt", "updatedAt", "escrow", "escrowStatus",
        "poster", "applicationsCount", "applicationCount", "isPaid", "paid",
    )
    return {key: item.get(key) for key in allowed if item.get(key) is not None}


def main() -> int:
    endpoints = {name: fetch(url) for name, url in URLS.items()}
    unique: dict[str, dict[str, Any]] = {}
    for source in ("jobs_default", "jobs_open_lower", "jobs_open_upper"):
        response = endpoints[source]
        for raw in unwrap(response.get("payload")):
            compact = compact_job(raw)
            identifier = str(compact.get("id") or json.dumps(compact, sort_keys=True))
            compact["observed_via"] = source
            unique[identifier] = compact

    skill_text = str(endpoints.get("skill", {}).get("text_preview") or "")
    api_lines = []
    for line in skill_text.splitlines():
        if re.search(r"(?:GET|POST|PATCH|DELETE)\s+https://openjobs\.bot/api|/api/", line, re.I):
            api_lines.append(line.strip())

    result = {
        "generated_at": now_iso(),
        "endpoints": endpoints,
        "job_count": len(unique),
        "jobs": list(unique.values()),
        "skill_api_lines": api_lines[:300],
        "writes_performed": [],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "jobs": len(unique), "skill_api_lines": len(api_lines)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
