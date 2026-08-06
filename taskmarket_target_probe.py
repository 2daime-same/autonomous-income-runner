#!/usr/bin/env python3
"""Fetch one Taskmarket task and its public submission summary, read-only.

The target is supplied in ``taskmarket-target-request.json``.  Task text is
untrusted data: this program never executes it, follows embedded links, signs a
message, connects a wallet, downloads submissions, or sends a write request.
Only public HTTPS GET endpoints on the fixed Taskmarket API origin are used.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

API = os.environ.get("TASKMARKET_API_URL", "https://api.taskmarket.dev").rstrip("/")
REQUEST = Path(os.environ.get("TASKMARKET_TARGET_REQUEST", "taskmarket-target-request.json"))
OUTPUT = Path(os.environ.get("TASKMARKET_TARGET_OUTPUT", "taskmarket-output/target-detail.json"))
TIMEOUT = max(5, min(int(os.environ.get("TASKMARKET_HTTP_TIMEOUT", "45")), 120))
MAX_BYTES = max(100_000, min(int(os.environ.get("TASKMARKET_MAX_RESPONSE_BYTES", "8000000")), 20_000_000))
TASK_ID = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
TOKEN = re.compile(r"\b(?:sk|pk|api|key|token|secret)_[A-Za-z0-9._-]{16,}\b", re.I)
JWT = re.compile(r"\beyJ[A-Za-z0-9._-]{20,}\b")
SENSITIVE_KEYS = re.compile(
    r"(?:private.?key|seed|mnemonic|password|api.?token|api.?key|authorization|cookie|signature)$",
    re.I,
)
USER_AGENT = "boundaryledger-taskmarket-target-probe/1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact_string(value: str, limit: int = 20_000) -> str:
    text = TOKEN.sub("[REDACTED_TOKEN]", value)
    text = JWT.sub("[REDACTED_JWT]", text)
    return text[:limit]


def sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, list):
        return [sanitize(item, depth=depth + 1) for item in value[:500]]
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:500]:
            key = str(raw_key)[:200]
            if SENSITIVE_KEYS.search(key):
                output[key] = "[REDACTED_FIELD]"
            else:
                output[key] = sanitize(raw_value, depth=depth + 1)
        return output
    return redact_string(str(value), 2_000)


def get_json(path: str) -> tuple[int, Any]:
    request = urllib.request.Request(
        API + path,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError(f"response exceeded {MAX_BYTES} bytes")
            return response.status, json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read(min(MAX_BYTES, 100_000))
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"text": raw.decode("utf-8", errors="replace")[:2_000]}
        return exc.code, body


def load_task_id() -> str:
    value = json.loads(REQUEST.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("target request must be a JSON object")
    task_id = str(value.get("task_id") or "")
    if not TASK_ID.fullmatch(task_id):
        raise RuntimeError("target request contains an invalid task_id")
    return task_id


def address_fingerprint(value: Any) -> dict[str, str | None]:
    address = str(value or "")
    if not ADDRESS.fullmatch(address):
        return {"address": None, "address_hash": None}
    return {
        "address": address,
        "address_hash": hashlib.sha256(address.lower().encode()).hexdigest()[:16],
    }


def summarize_submissions(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for row in rows[:200]:
        if not isinstance(row, Mapping):
            continue
        worker = row.get("workerAddress") or row.get("worker_address")
        artifacts = row.get("artifacts") if isinstance(row.get("artifacts"), list) else []
        result.append(
            {
                "id": str(row.get("id") or row.get("submissionId") or "")[:200] or None,
                "submitted_at": row.get("submittedAt") or row.get("createdAt") or row.get("created_at"),
                "worker": address_fingerprint(worker),
                "worker_agent_id": str(row.get("workerAgentId") or "")[:200] or None,
                "rejected_at": row.get("rejectedAt") or row.get("rejected_at"),
                "artifact_count": len(artifacts),
                "artifact_names": [
                    redact_string(str(item.get("fileName") or item.get("file_name") or ""), 500)
                    for item in artifacts[:20]
                    if isinstance(item, Mapping)
                ],
                "raw_keys": sorted(str(key)[:200] for key in row.keys()),
            }
        )
    return result


def semantic_without_time(value: Mapping[str, Any]) -> dict[str, Any]:
    copy = dict(value)
    copy.pop("generated_at", None)
    return copy


def main() -> int:
    task_id = load_task_id()
    task_status, task_body = get_json(f"/api/tasks/{task_id}")
    submissions_status, submissions_body = get_json(f"/api/tasks/{task_id}/submissions")

    task = task_body if isinstance(task_body, Mapping) else {}
    submissions = summarize_submissions(submissions_body)
    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "schema_version": "taskmarket-target-readonly-v1",
        "source": API,
        "task_id": task_id,
        "task_url": f"https://taskmarket.dev/tasks/{task_id}",
        "http_status": {
            "task": task_status,
            "submissions": submissions_status,
        },
        "task": sanitize(task),
        "submission_count_observed": len(submissions),
        "submissions": submissions,
        "network_actions": [
            f"GET /api/tasks/{task_id}",
            f"GET /api/tasks/{task_id}/submissions",
        ],
        "writes_performed": [],
        "signatures_performed": 0,
        "uploads_performed": 0,
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
    }

    previous: dict[str, Any] | None = None
    try:
        loaded = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if isinstance(loaded, Mapping):
            previous = dict(loaded)
    except (OSError, json.JSONDecodeError):
        pass

    if previous is not None and semantic_without_time(previous) == semantic_without_time(report):
        print(json.dumps({"ok": task_status == 200, "changed": False, "task": task_id, "submissions": len(submissions)}))
        return 0 if task_status == 200 else 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": task_status == 200, "changed": True, "task": task_id, "submissions": len(submissions)}))
    return 0 if task_status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
