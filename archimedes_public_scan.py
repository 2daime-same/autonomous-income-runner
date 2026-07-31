#!/usr/bin/env python3
"""Discover funded Archimedes engineering bounties through its public REST API.

This program is deliberately read-only. Bounty text is untrusted data: the
scanner never executes instructions, downloads deliverables, signs up, accepts
terms, submits work, or touches Stripe. It only records a sanitized opportunity
snapshot for later human/agent evaluation.
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

API = os.environ.get("ARCHIMEDES_PUBLIC_API_URL", "https://archimedes.market").rstrip("/")
OUTPUT = Path(os.environ.get("ARCHIMEDES_PUBLIC_OUTPUT", "archimedes-output/public-scan.json"))
PAGE_LIMIT = max(1, min(int(os.environ.get("ARCHIMEDES_PAGE_LIMIT", "50")), 50))
MAX_PAGES = max(1, min(int(os.environ.get("ARCHIMEDES_MAX_PAGES", "10")), 20))
TIMEOUT = max(5, min(int(os.environ.get("ARCHIMEDES_HTTP_TIMEOUT", "45")), 120))
USER_AGENT = "nexaworks-archimedes-readonly-scanner/1.0"
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
WS = re.compile(r"\s+")

HARD_RISKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("requires_physical_or_hardware_work", re.compile(r"\b(cad|eda|pcb|schematic|gerber|fpga|verilog|vhdl|firmware flashing|3d print|mechanical drawing|bill of materials|bom\b|hardware prototype|physical prototype|ship|shipping)\b", re.I)),
    ("requests_credentials_or_secrets", re.compile(r"\b(private key|seed phrase|mnemonic|password|api key|access token|session cookie|login credential)\b", re.I)),
    ("requires_purchase_or_paid_service", re.compile(r"\b(buy|purchase|deposit|stake|subscription|paid account|credit card|gas fee|spend money)\b", re.I)),
    ("requires_identity_or_location_action", re.compile(r"\b(kyc|government id|identity verification|in person|visit|phone call|call a person|record yourself|photograph yourself)\b", re.I)),
    ("regulated_or_high_stakes", re.compile(r"\b(medical diagnosis|legal representation|investment advice|gambling|weapon|controlled substance)\b", re.I)),
    ("requires_unavailable_media_production", re.compile(r"\b(shoot a video|film a video|video production|audio production|voice acting|wav\b|mp3\b|mp4\b|mov\b)\b", re.I)),
)

CAPABILITIES: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("python", re.compile(r"\bpython\b", re.I), 18.0),
    ("typescript_javascript", re.compile(r"\b(typescript|javascript|node(?:\.js)?|react|next(?:\.js)?)\b", re.I), 18.0),
    ("api_backend", re.compile(r"\b(api|rest|graphql|backend|server|webhook|database|postgres|sqlite)\b", re.I), 15.0),
    ("mcp_agent", re.compile(r"\b(mcp|model context protocol|ai agent|llm|tool server)\b", re.I), 20.0),
    ("testing_debugging", re.compile(r"\b(test|testing|bug|debug|fix|validation|benchmark|ci|github actions)\b", re.I), 12.0),
    ("research_data", re.compile(r"\b(research|analysis|dataset|data cleaning|evaluation|report|evidence)\b", re.I), 10.0),
    ("documentation", re.compile(r"\b(documentation|docs|tutorial|technical writing|readme|markdown)\b", re.I), 8.0),
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: Any, limit: int = 4000) -> str:
    text = WS.sub(" ", str(value or "")).strip()
    text = re.sub(r"\b(?:sk|pk|api|key|token)_[A-Za-z0-9._~+/=-]{12,}\b", "[REDACTED_TOKEN]", text)
    text = re.sub(r"\b0x[0-9a-fA-F]{64}\b", "[REDACTED_HEX]", text)
    return text[:limit]


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def get_json(path: str, query: Mapping[str, Any] | None = None) -> Any:
    url = f"{API}{path}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {path} returned HTTP {response.status}")
        raw = response.read(8_000_000)
    return json.loads(raw.decode("utf-8"))


def fetch_open_bounties() -> tuple[list[Mapping[str, Any]], list[str]]:
    rows: list[Mapping[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for page in range(MAX_PAGES):
        offset = page * PAGE_LIMIT
        try:
            payload = get_json(
                "/api/public/bounties",
                {"status": "open", "limit": PAGE_LIMIT, "offset": offset},
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            errors.append(f"list offset {offset}: {type(exc).__name__}: {clean(exc, 300)}")
            break
        items = payload.get("items", []) if isinstance(payload, Mapping) else []
        if not isinstance(items, list):
            errors.append("Unexpected bounty-list response: items is not a list")
            break
        for item in items:
            if not isinstance(item, Mapping):
                continue
            bounty_id = str(item.get("id") or "")
            if bounty_id in seen:
                continue
            seen.add(bounty_id)
            rows.append(item)
        total = int(payload.get("total") or 0) if isinstance(payload, Mapping) else 0
        if len(items) < PAGE_LIMIT or offset + len(items) >= total:
            break
    return rows, errors


def fetch_detail(bounty_id: str) -> tuple[Mapping[str, Any] | None, str | None]:
    if not UUID.fullmatch(bounty_id):
        return None, "invalid bounty UUID"
    try:
        payload = get_json(f"/api/public/bounties/{urllib.parse.quote(bounty_id)}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {clean(exc, 300)}"
    if not isinstance(payload, Mapping):
        return None, "detail response is not an object"
    return payload, None


def text_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for item in value.values():
            values.extend(text_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(text_values(item))
    elif isinstance(value, str):
        values.append(value)
    return values


def urgency_bucket(deadline: datetime | None, now: datetime) -> str:
    if deadline is None:
        return "unknown"
    hours = (deadline - now).total_seconds() / 3600
    if hours <= 0:
        return "expired"
    if hours < 24:
        return "under_24h"
    if hours < 72:
        return "1_to_3_days"
    if hours < 168:
        return "3_to_7_days"
    if hours < 720:
        return "1_to_30_days"
    return "over_30_days"


def normalized_requirements(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in detail.get("requirements") or []:
        if not isinstance(item, Mapping):
            continue
        output.append({
            "description": clean(item.get("description"), 900),
            "category": clean(item.get("category"), 80) or None,
            "priority": clean(item.get("priority"), 80) or None,
        })
    return output[:40]


def normalized_deliverables(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in detail.get("deliverables") or []:
        if not isinstance(item, Mapping):
            continue
        formats = [clean(fmt, 40) for fmt in (item.get("accepted_formats") or []) if clean(fmt, 40)]
        output.append({
            "name": clean(item.get("name"), 180),
            "type": clean(item.get("type"), 80),
            "required": bool(item.get("required")),
            "description": clean(item.get("description"), 700) or None,
            "accepted_formats": formats[:20],
        })
    return output[:30]


def normalized_tests(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in detail.get("acceptance_tests") or []:
        if not isinstance(item, Mapping):
            continue
        output.append({
            "name": clean(item.get("name"), 180),
            "test_type": clean(item.get("test_type"), 80),
            "required": bool(item.get("required")),
            "description": clean(item.get("description"), 700) or None,
        })
    return output[:30]


def classify(summary: Mapping[str, Any], detail: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    bounty_id = str(detail.get("id") or summary.get("id") or "")
    title = clean(detail.get("title") or summary.get("title"), 260)
    description = clean(detail.get("description") or summary.get("summary"), 3000)
    category = clean(detail.get("category") or summary.get("category"), 80).lower()
    complexity = clean(detail.get("complexity") or summary.get("complexity"), 80).lower()
    status = clean(detail.get("status") or summary.get("status"), 40).lower()
    escrow_status = clean(detail.get("escrow_status") or summary.get("escrow_status"), 40).lower()
    funded = bool(detail.get("is_funded") if "is_funded" in detail else summary.get("is_funded"))
    try:
        price_cents = max(0, int(detail.get("price_cents") or summary.get("price_cents") or 0))
    except (TypeError, ValueError, OverflowError):
        price_cents = 0
    deadline = parse_time(detail.get("deadline_iso") or summary.get("deadline_iso"))
    requirements = normalized_requirements(detail)
    deliverables = normalized_deliverables(detail)
    tests = normalized_tests(detail)
    corpus = " ".join([title, description, category, complexity, *text_values(requirements), *text_values(deliverables), *text_values(tests)])
    hard_risks = [name for name, pattern in HARD_RISKS if pattern.search(corpus)]
    capabilities = [name for name, pattern, _ in CAPABILITIES if pattern.search(corpus)]

    reasons: list[str] = []
    if not UUID.fullmatch(bounty_id):
        reasons.append("invalid_bounty_id")
    if status != "open":
        reasons.append("not_open")
    if not funded or escrow_status != "locked":
        reasons.append("funds_not_confirmed_locked")
    if price_cents <= 0:
        reasons.append("no_positive_payout")
    if deadline is None or deadline <= now:
        reasons.append("expired_or_unknown_deadline")
    if category in {"hardware", "creative", "cad", "eda"}:
        reasons.append("unsupported_category")
    reasons.extend(hard_risks)

    score = min(price_cents / 100.0, 5000.0) / 10.0
    score += sum(bonus for _name, pattern, bonus in CAPABILITIES if pattern.search(corpus))
    score += min(len(tests), 8) * 2.0
    score += min(len(deliverables), 8) * 1.5
    if category in {"software", "mcp", "documentation"}:
        score += 20
    elif category == "research":
        score += 8
    if complexity in {"expert", "advanced", "very high"}:
        score -= 20
    elif complexity in {"high", "complex"}:
        score -= 10
    bucket = urgency_bucket(deadline, now)
    score += {
        "under_24h": -60,
        "1_to_3_days": -30,
        "3_to_7_days": -10,
        "1_to_30_days": 8,
        "over_30_days": 4,
        "expired": -100,
        "unknown": -100,
    }[bucket]
    score -= len(hard_risks) * 50
    viable = not reasons and bool(capabilities) and score > 0

    return {
        "id": bounty_id,
        "display_id": clean(detail.get("display_id") or summary.get("display_id"), 80) or None,
        "title": title,
        "summary": clean(detail.get("summary") or summary.get("summary"), 900),
        "description_excerpt": description[:1200],
        "category": category or None,
        "complexity": complexity or None,
        "status": status,
        "escrow_status": escrow_status,
        "is_funded": funded,
        "payout_usd": round(price_cents / 100.0, 2),
        "deadline": iso(deadline) if deadline else None,
        "urgency_bucket": bucket,
        "url": clean(detail.get("url") or summary.get("url"), 500) or None,
        "capability_matches": capabilities,
        "requirements": requirements,
        "deliverables": deliverables,
        "acceptance_tests": tests,
        "hard_exclusion_reasons": sorted(set(reasons)),
        "score": round(score, 2),
        "candidate": viable,
    }


def load_previous_semantic() -> dict[str, Any] | None:
    try:
        previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(previous, dict):
        return None
    previous.pop("generated_at", None)
    return previous


def main() -> int:
    now = now_utc()
    summaries, errors = fetch_open_bounties()
    classified: list[dict[str, Any]] = []
    for summary in summaries:
        bounty_id = str(summary.get("id") or "")
        detail, error = fetch_detail(bounty_id)
        if error or detail is None:
            errors.append(f"detail {bounty_id or '[missing]'}: {error or 'unknown error'}")
            continue
        classified.append(classify(summary, detail, now))

    ranked = sorted(classified, key=lambda item: (item["candidate"], item["score"], item["payout_usd"]), reverse=True)
    candidates = [item for item in ranked if item["candidate"]]
    excluded = [item for item in ranked if not item["candidate"]]
    semantic: dict[str, Any] = {
        "source": f"{API}/api/public/bounties (GET only)",
        "safety": "Read-only public scan; no account, terms acceptance, Stripe onboarding, claim, upload, submission, payment, or download.",
        "geographic_note": "Platform terms say access from outside the United States may be limited; no registration or participation was attempted.",
        "verified_income_usd": 0,
        "open_summaries_fetched": len(summaries),
        "details_fetched": len(classified),
        "candidate_count": len(candidates),
        "errors": errors,
        "ranked_candidates": candidates[:25],
        "excluded": excluded[:50],
    }
    if load_previous_semantic() == semantic:
        print(json.dumps({"ok": True, "changed": False, "open": len(summaries), "candidates": len(candidates)}))
        return 0
    report = {"generated_at": iso(now), **semantic}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"ok": True, "changed": True, "open": len(summaries), "candidates": len(candidates)}))
    return 0 if summaries or not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
