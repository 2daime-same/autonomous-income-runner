#!/usr/bin/env python3
"""Inspect MoltJobs open inventory through its public read endpoints.

No registration, bid, wallet, or mutation is performed. Full job objects are
preserved after credential-shaped values are recursively redacted.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE = "https://api.moltjobs.io/v1"
OUTPUT = Path(os.environ.get("MOLTJOBS_INSPECTION_OUTPUT", "market-output/moltjobs-open-details.json"))
TIMEOUT = 45

SECRET_KEYS = {
    "api_key",
    "apikey",
    "rawkey",
    "authorization",
    "access_token",
    "refresh_token",
    "private_key",
    "secret",
    "token",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            result[key] = "[REDACTED]" if normalized in SECRET_KEYS else sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\bmj_(?:live|test)_[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


def get(path: str, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
    url = BASE + path
    if query:
        url += "?" + urllib.parse.urlencode({key: value for key, value in query.items() if value is not None})
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "nexaworks-autonomous-income-moltjobs-inspector/1.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else None
            return {"ok": True, "status": response.status, "url": response.geturl(), "payload": sanitize(payload)}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw[:5000]
        return {"ok": False, "status": error.code, "url": url, "payload": sanitize(payload)}
    except Exception as error:
        return {"ok": False, "url": url, "error": f"{type(error).__name__}: {error}"}


def unwrap_data(value: Any) -> Any:
    if isinstance(value, Mapping) and "data" in value:
        return value.get("data")
    return value


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> int:
    list_result = get("/jobs", {"status": "OPEN", "limit": 100})
    jobs_value = unwrap_data(list_result.get("payload"))
    jobs = [item for item in jobs_value if isinstance(item, Mapping)] if isinstance(jobs_value, list) else []

    details = []
    template_ids: set[str] = set()
    now = datetime.now(timezone.utc)
    for job in jobs:
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        detail = get("/public/jobs/" + urllib.parse.quote(job_id, safe=""))
        payload = unwrap_data(detail.get("payload"))
        if isinstance(payload, Mapping):
            template_id = payload.get("templateId") or payload.get("template_id")
            if template_id:
                template_ids.add(str(template_id))
        deadline = parse_time(job.get("deadlineAt") or job.get("deadline_at"))
        details.append(
            {
                "list_item": sanitize(job),
                "public_detail_response": detail,
                "deadline_future": deadline is None or deadline > now,
                "escrow_evidence_present": bool(
                    job.get("escrowTxHash")
                    or job.get("escrowJobId")
                    or job.get("cardCapturedAt")
                    or job.get("paymentStatus") in {"FUNDED", "CAPTURED", "ESCROWED"}
                ),
            }
        )

    templates = {
        template_id: get("/templates/" + urllib.parse.quote(template_id, safe=""))
        for template_id in sorted(template_ids)
    }
    auxiliary = {
        "stats": get("/stats"),
        "activity": get("/activity", {"limit": 50}),
        "templates": get("/templates", {"limit": 100}),
        "agents": get("/agents", {"limit": 20, "sort": "reputation"}),
    }

    result = {
        "generated_at": now_iso(),
        "base_url": BASE,
        "open_job_count": len(jobs),
        "list_response": list_result,
        "job_details": details,
        "referenced_templates": templates,
        "auxiliary": auxiliary,
        "writes_performed": [],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "open_jobs": len(jobs), "templates": len(template_ids)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())