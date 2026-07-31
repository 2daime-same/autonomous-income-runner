#!/usr/bin/env python3
"""Read and rank Taskmarket opportunities without wallets, signatures, or writes.

All task text is untrusted data. This scanner performs GET requests only, never
executes task content, and records a compact, sanitized public snapshot.
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

API = os.environ.get("TASKMARKET_API_URL", "https://api.taskmarket.dev").rstrip("/")
OUTPUT = Path(os.environ.get("TASKMARKET_PUBLIC_OUTPUT", "taskmarket-output/public-scan.json"))
MAX_PAGES = max(1, min(int(os.environ.get("TASKMARKET_MAX_PAGES", "10")), 50))
PAGE_LIMIT = max(1, min(int(os.environ.get("TASKMARKET_PAGE_LIMIT", "100")), 100))
TIMEOUT = max(5, min(int(os.environ.get("TASKMARKET_HTTP_TIMEOUT", "45")), 120))
USER_AGENT = "nexaworks-taskmarket-readonly-scanner/1.0"
TASK_ID = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
WS = re.compile(r"\s+")

HARD_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("requires_purchase_or_funding", re.compile(r"\b(buy|purchase|pay for|fund|deposit|stake|gas fee|subscription|spend)\b", re.I)),
    ("requests_credentials_or_secrets", re.compile(r"\b(private key|seed phrase|password|api key|access token|cookie|login credential|mnemonic)\b", re.I)),
    ("requires_account_or_social_action", re.compile(r"\b(create an account|sign up|log in|tweet|post on|linkedin|discord|telegram|send an email|make a call|phone call)\b", re.I)),
    ("requires_physical_or_location_action", re.compile(r"\b(ship|shipping|mail a|visit in person|photograph yourself|record yourself|physical product)\b", re.I)),
    ("requires_paid_media_model", re.compile(r"\b(suno|udio|veo|kling|runway|seedance|text-to-video|image-to-video|real audio model)\b", re.I)),
)
SOFT_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("external_code_or_file", re.compile(r"https?://|github|gist|download|repository|repo\b", re.I)),
    ("security_sensitive", re.compile(r"\b(exploit|malware|credential|scrape personal|bypass|phishing|vulnerability)\b", re.I)),
    ("regulated_or_high_stakes", re.compile(r"\b(medical diagnosis|legal advice|investment advice|gambling|cannabis|weapon)\b", re.I)),
    ("subjective_media_contest", re.compile(r"\b(video|film|music|audio|poster|logo|illustration|artwork|voice|photograph)\b", re.I)),
)
CAPABILITY_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("code", re.compile(r"\b(html|css|javascript|typescript|python|node(?:\.js)?|react|api|script|app|service|bug|test|cli|csv|json)\b", re.I), 18.0),
    ("research", re.compile(r"\b(research|analysis|assessment|report|evidence|dataset|data|fact[- ]check|compare)\b", re.I), 13.0),
    ("writing", re.compile(r"\b(write|article|documentation|tutorial|copy|summary|brief|markdown)\b", re.I), 7.0),
    ("design", re.compile(r"\b(design|poster|logo|illustration|image|artwork)\b", re.I), -3.0),
    ("audio_video", re.compile(r"\b(audio|music|video|film|wav|mp3|voice|animation)\b", re.I), -28.0),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: Any, limit: int = 1000) -> str:
    text = WS.sub(" ", str(value or "")).strip()
    text = re.sub(r"\b0x[0-9a-fA-F]{64}\b", "[REDACTED_HEX]", text)
    text = re.sub(r"\b(?:sk|pk|api|key|token)_[A-Za-z0-9_-]{16,}\b", "[REDACTED_TOKEN]", text)
    return text[:limit]


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def usdc(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("amount", "value", "reward"):
            if key in value:
                return usdc(value[key])
        return 0.0
    try:
        amount = float(str(value))
    except (TypeError, ValueError):
        return 0.0
    if abs(amount) >= 10_000:
        amount /= 1_000_000
    return round(amount, 6)


def parse_expiry(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        try:
            return datetime.fromtimestamp(stamp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def request_json(path: str, query: Mapping[str, Any] | None = None) -> Any:
    url = f"{API}{path}"
    if query:
        encoded = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None}, doseq=True)
        url = f"{url}?{encoded}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {path} returned HTTP {response.status}")
        raw = response.read(8_000_000)
    return json.loads(raw.decode("utf-8"))


def fetch_open_tasks() -> tuple[list[Mapping[str, Any]], list[str]]:
    tasks: list[Mapping[str, Any]] = []
    errors: list[str] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        try:
            payload = request_json(
                "/api/tasks",
                {"status": "open", "phase": "active", "sort": "newest", "limit": PAGE_LIMIT, "cursor": cursor},
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            errors.append(f"{type(exc).__name__}: {clean_text(exc, 300)}")
            break
        rows = payload.get("tasks", []) if isinstance(payload, Mapping) else []
        if not isinstance(rows, list):
            errors.append("Unexpected /api/tasks response: tasks is not a list")
            break
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            task_id = str(row.get("id") or row.get("taskId") or "")
            dedupe = task_id or json.dumps(row, sort_keys=True, default=str)[:500]
            if dedupe in seen:
                continue
            seen.add(dedupe)
            tasks.append(row)
        next_cursor = payload.get("nextCursor") if isinstance(payload, Mapping) else None
        if not payload.get("hasMore") or not next_cursor or next_cursor == cursor:
            break
        cursor = str(next_cursor)
    return tasks, errors


def task_title(task: Mapping[str, Any]) -> str:
    description = clean_text(task.get("description"), 1000)
    explicit = clean_text(task.get("title") or task.get("name"), 240)
    if explicit:
        return explicit
    first = re.split(r"[\n.!?]", description, maxsplit=1)[0].strip()
    return (first or description or "Untitled task")[:180]


def classify(task: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    task_id = str(task.get("id") or task.get("taskId") or "")
    description = clean_text(task.get("description"), 1600)
    title = task_title(task)
    haystack = f"{title} {description} {' '.join(map(str, task.get('tags') or []))}"
    mode = clean_text(task.get("mode"), 40).lower()
    status = clean_text(task.get("status"), 40).lower()
    reward = usdc(task.get("reward"))
    submissions = max(0, to_int(task.get("submissionCount")))
    pitches = max(0, to_int(task.get("pitchCount")))
    expiry = parse_expiry(task.get("expiryTime") or task.get("expiresAt"))
    hours_left = None if expiry is None else round((expiry - now).total_seconds() / 3600, 2)
    submission_window = bool(task.get("submissionWindowOpen"))
    hard_risks = [name for name, pattern in HARD_RISK_PATTERNS if pattern.search(haystack)]
    soft_risks = [name for name, pattern in SOFT_RISK_PATTERNS if pattern.search(haystack)]
    capabilities = [name for name, pattern, _ in CAPABILITY_PATTERNS if pattern.search(haystack)]

    reasons: list[str] = []
    if not TASK_ID.fullmatch(task_id):
        reasons.append("invalid_task_id")
    if status != "open":
        reasons.append("not_open")
    if hours_left is None or hours_left <= 0:
        reasons.append("expired_or_unknown_deadline")
    if mode not in {"bounty", "claim"}:
        reasons.append("entry_requires_payment_or_selection")
    if mode == "bounty" and not submission_window:
        reasons.append("submission_window_closed")
    if mode == "claim" and "pendingActions" in task and not any(
        isinstance(action, Mapping)
        and action.get("action") == "claim"
        and not action.get("requiresPayment")
        for action in (task.get("pendingActions") or [])
    ):
        reasons.append("claim_not_currently_available")
    if reward <= 0:
        reasons.append("no_positive_reward")
    if hard_risks:
        reasons.extend(hard_risks)

    score = min(reward, 100.0) * 4.0 - submissions * 1.35 - pitches
    score -= len(soft_risks) * 8.0 + len(hard_risks) * 40.0
    for _name, pattern, bonus in CAPABILITY_PATTERNS:
        if pattern.search(haystack):
            score += bonus
    if hours_left is not None:
        if hours_left < 2:
            score -= 35
        elif hours_left < 8:
            score -= 18
        elif hours_left <= 72:
            score += 8
        elif hours_left <= 168:
            score += 3
    if submissions == 0:
        score += 25
    elif submissions <= 2:
        score += 18
    elif submissions <= 5:
        score += 10
    elif submissions >= 25:
        score -= 10
    if mode == "claim":
        score += 18
    viable = not reasons and score > 0

    requester = clean_text(task.get("requester"), 80)
    if requester and not ADDRESS.fullmatch(requester):
        requester = "[INVALID_ADDRESS]"
    return {
        "task_id": task_id,
        "task_url": f"https://taskmarket.dev/dashboard/tasks/{task_id}" if TASK_ID.fullmatch(task_id) else None,
        "title": title,
        "description_excerpt": description[:600],
        "mode": mode,
        "status": status,
        "requester": requester or None,
        "requester_actor_type": clean_text(task.get("requesterActorType"), 30) or None,
        "reward_usdc": reward,
        "net_reward_usdc": usdc(task.get("netReward")),
        "platform_fee_bps": to_int(task.get("platformFeeBps")),
        "expiry": iso(expiry) if expiry else None,
        "hours_left": hours_left,
        "submission_count": submissions,
        "pitch_count": pitches,
        "submission_window_open": submission_window,
        "tags": [clean_text(tag, 80) for tag in (task.get("tags") or []) if clean_text(tag, 80)][:20],
        "capability_matches": capabilities,
        "soft_risks": soft_risks,
        "hard_exclusion_reasons": sorted(set(reasons)),
        "score": round(score, 2),
        "zero_spend_candidate": viable,
    }


def load_previous_semantic() -> dict[str, Any] | None:
    try:
        value = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    value.pop("generated_at", None)
    return value


def main() -> int:
    now = utcnow()
    tasks, errors = fetch_open_tasks()
    classified = [classify(task, now) for task in tasks]
    ranked = sorted(classified, key=lambda item: (item["zero_spend_candidate"], item["score"], item["reward_usdc"]), reverse=True)
    viable = [item for item in ranked if item["zero_spend_candidate"]]
    excluded = [item for item in ranked if not item["zero_spend_candidate"]]
    semantic: dict[str, Any] = {
        "source": f"{API}/api/tasks (GET only)",
        "safety": "Public read-only scan; no wallet, legal acceptance, signature, payment, claim, pitch, bid, proof, submission, or download.",
        "verified_income_usdc": 0,
        "pages_limit": MAX_PAGES,
        "fetched_open_active_tasks": len(tasks),
        "zero_spend_candidate_count": len(viable),
        "errors": errors,
        "ranked_candidates": viable[:25],
        "excluded_sample": excluded[:25],
    }
    if load_previous_semantic() == semantic:
        print(json.dumps({"ok": True, "changed": False, "tasks": len(tasks), "candidates": len(viable)}))
        return 0
    report = {"generated_at": iso(now), **semantic}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"ok": True, "changed": True, "tasks": len(tasks), "candidates": len(viable)}))
    return 0 if tasks or not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
