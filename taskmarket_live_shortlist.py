#!/usr/bin/env python3
"""Build a current, read-only shortlist of Taskmarket tasks that still accept direct submissions.

Task descriptions are untrusted data. This script performs GET requests only and never
executes links or task instructions, signs messages, creates wallets, uploads files, or
submits work.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

API = os.environ.get("TASKMARKET_API_URL", "https://api.taskmarket.dev").rstrip("/")
OUTPUT = Path(os.environ.get("TASKMARKET_LIVE_SHORTLIST_OUTPUT", "taskmarket-output/live-open-shortlist.json"))
MAX_PAGES = max(1, min(int(os.environ.get("TASKMARKET_MAX_PAGES", "10")), 50))
LIMIT = max(1, min(int(os.environ.get("TASKMARKET_PAGE_LIMIT", "100")), 100))
TIMEOUT = max(5, min(int(os.environ.get("TASKMARKET_HTTP_TIMEOUT", "45")), 120))
TASK_ID = re.compile(r"^0x[0-9a-fA-F]{64}$")
WS = re.compile(r"\s+")
TOKEN = re.compile(r"\b(?:sk|pk|api|key|token|secret)_[A-Za-z0-9._-]{16,}\b", re.I)
JWT = re.compile(r"\beyJ[A-Za-z0-9._-]{20,}\b")

# These are warnings, not automatic instructions. Human/agent review decides whether a task is safe.
WARNING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("possible_owner_asset_outflow", re.compile(r"\b(?:buy|purchase|deposit|stake|gas fee|pay for|fund (?:a|the|this)|send (?:money|funds|crypto)|create and fund)\b", re.I)),
    ("account_or_contact_action", re.compile(r"\b(?:create an account|sign up|log in|contact the project|send an email|tweet|post on|discord|telegram)\b", re.I)),
    ("credential_or_secret_request", re.compile(r"\b(?:private key|seed phrase|mnemonic|password|api key|access token|cookie)\b", re.I)),
    ("physical_or_location_action", re.compile(r"\b(?:ship|mail a|visit in person|record yourself|photograph yourself|physical product)\b", re.I)),
    ("subjective_media_or_design", re.compile(r"\b(?:video|film|music|audio|poster|logo|illustration|artwork|photograph|three\.js|arcade game)\b", re.I)),
    ("external_repository_or_download", re.compile(r"https?://|\b(?:github|repository|repo|download|clone)\b", re.I)),
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            stamp = float(value)
            if stamp > 10_000_000_000:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def clean(value: Any, limit: int = 4000) -> str:
    text = WS.sub(" ", str(value or "")).strip()
    text = TOKEN.sub("[REDACTED_TOKEN]", text)
    text = JWT.sub("[REDACTED_JWT]", text)
    return text[:limit]


def amount_usdc(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("amount", "value", "reward"):
            if key in value:
                return amount_usdc(value[key])
        return 0.0
    try:
        number = float(str(value))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if abs(number) >= 10_000:
        number /= 1_000_000
    return round(number, 6)


def integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def get_page(cursor: str | None) -> Mapping[str, Any]:
    query = urllib.parse.urlencode({
        "status": "open",
        "phase": "active",
        "sort": "newest",
        "limit": LIMIT,
        **({"cursor": cursor} if cursor else {}),
    })
    request = urllib.request.Request(
        f"{API}/api/tasks?{query}",
        headers={"Accept": "application/json", "User-Agent": "boundaryledger-taskmarket-live-shortlist/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(12_000_000)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("Taskmarket tasks response was not an object")
    return value


def pending_actions(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for action in task.get("pendingActions") or []:
        if not isinstance(action, Mapping):
            continue
        result.append({
            "action": clean(action.get("action"), 80) or None,
            "role": clean(action.get("role"), 40) or None,
            "requires_payment": bool(action.get("requiresPayment")),
            "payment_amount_raw": clean(action.get("paymentAmount"), 80) or None,
            "available_until": clean(action.get("availableUntil"), 80) or None,
        })
    return result[:30]


def summarize(task: Mapping[str, Any], current: datetime) -> dict[str, Any] | None:
    task_id = str(task.get("id") or task.get("taskId") or "")
    expiry = parse_time(task.get("expiryTime") or task.get("expiresAt"))
    reward = amount_usdc(task.get("reward"))
    status = clean(task.get("status"), 30).lower()
    phase = clean(task.get("phase"), 30).lower()
    window = bool(task.get("submissionWindowOpen"))
    stake_required = bool(task.get("stakeRequired")) or integer(task.get("stakeBps")) > 0
    if not TASK_ID.fullmatch(task_id):
        return None
    if status != "open" or phase != "active" or not window or reward <= 0 or expiry is None or expiry <= current or stake_required:
        return None

    description = clean(task.get("description"), 6000)
    title = clean(task.get("title") or task.get("name"), 300)
    if not title:
        title = re.split(r"[.!?]", description, maxsplit=1)[0][:240] or "Untitled task"
    warnings = [name for name, pattern in WARNING_PATTERNS if pattern.search(f"{title} {description}")]
    actions = pending_actions(task)
    worker_payment_actions = [
        item for item in actions
        if item.get("role") == "worker" and item.get("requires_payment")
    ]
    return {
        "task_id": task_id,
        "task_url": f"https://taskmarket.dev/tasks/{task_id}",
        "title": title,
        "description": description,
        "mode": clean(task.get("mode"), 40).lower(),
        "reward_usdc": reward,
        "net_reward_usdc": amount_usdc(task.get("netReward")),
        "platform_fee_bps": integer(task.get("platformFeeBps")),
        "expiry": expiry.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "hours_left": round((expiry - current).total_seconds() / 3600, 2),
        "submission_count": integer(task.get("submissionCount")),
        "pitch_count": integer(task.get("pitchCount")),
        "requester_actor_type": clean(task.get("requesterActorType"), 40) or None,
        "worker_agent_id": clean(task.get("workerAgentId"), 120) or None,
        "self_award": bool(task.get("selfAward")),
        "warnings": warnings,
        "pending_actions": actions,
        "worker_payment_action_count": len(worker_payment_actions),
        "direct_zero_payment_submission_candidate": len(worker_payment_actions) == 0,
        "tags": [clean(tag, 80) for tag in (task.get("tags") or [])][:20],
    }


def main() -> int:
    current = now()
    cursor: str | None = None
    seen: set[str] = set()
    rows: list[Mapping[str, Any]] = []
    errors: list[str] = []
    for _ in range(MAX_PAGES):
        try:
            page = get_page(cursor)
        except Exception as exc:  # noqa: BLE001 - public error is sanitized below
            errors.append(f"{type(exc).__name__}: {clean(exc, 400)}")
            break
        for row in page.get("tasks") or []:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("id") or row.get("taskId") or "")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        next_cursor = page.get("nextCursor")
        if not page.get("hasMore") or not next_cursor or str(next_cursor) == cursor:
            break
        cursor = str(next_cursor)

    candidates = [item for item in (summarize(row, current) for row in rows) if item is not None]
    candidates.sort(key=lambda item: (
        item["worker_payment_action_count"],
        len(item["warnings"]),
        item["submission_count"],
        -item["net_reward_usdc"],
        -item["hours_left"],
    ))
    report = {
        "generated_at": current.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": f"{API}/api/tasks (GET only)",
        "fetched_open_active_tasks": len(rows),
        "accepting_direct_submissions_count": len(candidates),
        "zero_payment_route_count": sum(item["direct_zero_payment_submission_candidate"] for item in candidates),
        "errors": errors,
        "candidates": candidates[:100],
        "writes_performed": [],
        "signatures_performed": 0,
        "uploads_performed": 0,
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": not errors, "tasks": len(rows), "candidates": len(candidates)}))
    return 0 if candidates or not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
