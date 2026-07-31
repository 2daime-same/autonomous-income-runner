#!/usr/bin/env python3
"""Read-only probe for genuinely open TaskBounty tasks after the filter fix."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE = "https://www.task-bounty.com/api/v1"
OUTPUT = Path("market-output/taskbounty-live.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_json(path: str) -> tuple[int, Any]:
    req = urllib.request.Request(
        BASE + path,
        headers={"Accept": "application/json", "User-Agent": "boundaryledger-taskbounty-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"text": raw[:1000]}
        return exc.code, payload


def tasks_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("tasks", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                return [dict(item) for item in payload[key] if isinstance(item, Mapping)]
    return []


def scalar(item: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in item and item[name] not in (None, ""):
            return item[name]
    return None


def normalized_state(task: Mapping[str, Any]) -> str:
    return str(scalar(task, "state", "status", "task_state") or "UNKNOWN").upper()


def is_open(task: Mapping[str, Any]) -> bool:
    state = normalized_state(task)
    if state not in {"OPEN", "AVAILABLE", "ACTIVE", "UNCLAIMED"}:
        return False
    terminal_fields = ("winner_id", "winnerId", "awarded_at", "awardedAt", "closed_at", "closedAt", "completed_at", "completedAt")
    if any(task.get(field) not in (None, "", False) for field in terminal_fields):
        return False
    if task.get("submissions_are_accepted") is False or task.get("accepting_submissions") is False:
        return False
    return True


def compact(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": scalar(task, "id", "task_id", "taskId"),
        "title": scalar(task, "title", "name"),
        "state": normalized_state(task),
        "bounty": scalar(task, "bounty", "bounty_usd", "reward", "amount", "price"),
        "currency": scalar(task, "currency", "payout_currency"),
        "language": scalar(task, "language", "primary_language"),
        "github_issue_url": scalar(task, "github_issue_url", "githubIssueUrl", "issue_url", "issueUrl"),
        "github_repo_url": scalar(task, "github_repo_url", "githubRepoUrl", "repo_url", "repoUrl"),
        "deadline": scalar(task, "deadline", "expires_at", "expiresAt"),
        "created_at": scalar(task, "created_at", "createdAt"),
    }


def main() -> int:
    query = urllib.parse.urlencode({"state": "open", "limit": 100})
    status, payload = get_json(f"/tasks?{query}")
    tasks = tasks_from(payload)
    open_tasks = [task for task in tasks if is_open(task)]
    details: list[dict[str, Any]] = []
    for task in open_tasks[:10]:
        task_id = scalar(task, "id", "task_id", "taskId")
        detail_status = None
        detail_payload = None
        if task_id:
            detail_status, detail_payload = get_json(f"/tasks/{urllib.parse.quote(str(task_id))}")
        details.append({
            **compact(task),
            "detail_http_status": detail_status,
            "detail_available_without_auth": detail_status == 200,
            "detail_shape_keys": sorted(detail_payload.keys())[:40] if isinstance(detail_payload, Mapping) else [],
        })
    result = {
        "generated_at": now_iso(),
        "endpoint": f"{BASE}/tasks?{query}",
        "http_status": status,
        "returned_task_count": len(tasks),
        "returned_states": sorted({normalized_state(task) for task in tasks}),
        "genuinely_open_count": len(open_tasks),
        "actionable": details,
        "all_returned": [compact(task) for task in tasks[:100]],
        "writes_performed": [],
        "authentication_used": False,
        "expenses_usd": 0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"ok": status == 200, "returned": len(tasks), "open": len(open_tasks)}))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
