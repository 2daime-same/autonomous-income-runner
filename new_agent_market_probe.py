#!/usr/bin/env python3
"""Read-only discovery for newly identified AI-agent work markets.

This probe performs GET requests only. It does not register, sign, bid, claim,
submit, pay, create a wallet, accept terms, or withdraw funds. It extracts
machine-checkable public inventory and rejects opportunities that require
spending, referrals, social posting, physical access, or unverifiable payment.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

OUTPUT = Path(os.environ.get("NEW_AGENT_MARKET_OUTPUT", "market-output/new-agent-markets.json"))
TIMEOUT = 40
MAX_BYTES = 600_000

SEEDS: dict[str, list[str]] = {
    "worq": [
        "https://worq.dev/skill.md",
        "https://worq.dev/openapi.json",
        "https://api.worq.dev/openapi.json",
        "https://api.worq.dev/v1/jobs?status=open&limit=100",
        "https://api.worq.dev/v1/jobs?status=OPEN&limit=100",
    ],
    "agrenting": [
        "https://agrenting.com/skill.md",
        "https://agrenting.com/openapi.json",
        "https://agrenting.com/api/v1/jobs?status=open&limit=100",
        "https://agrenting.com/api/jobs?status=open&limit=100",
        "https://api.agrenting.com/v1/jobs?status=open&limit=100",
    ],
    "agentjob": [
        "https://agent-job.ai/skill.md",
        "https://agent-job.ai/openapi.json",
        "https://agent-job.ai/api/v1/jobs?status=open&limit=100",
        "https://agent-job.ai/api/jobs?status=open&limit=100",
        "https://api.agent-job.ai/v1/jobs?status=open&limit=100",
    ],
    "clawlancer": [
        "https://clawlancer.ai/api/info",
        "https://clawlancer.ai/docs",
        "https://clawlancer.ai/skill.md",
        "https://clawlancer.ai/openapi.json",
        "https://clawlancer.ai/api/v1/jobs?status=open&limit=100",
        "https://clawlancer.ai/api/jobs?status=open&limit=100",
        "https://clawlancer.ai/api/bounties?status=open&limit=100",
        "https://clawlancer.ai/api/tasks?status=open&limit=100",
    ],
    "callboard": [
        "https://getcallboard.com/skill.md",
        "https://getcallboard.com/openapi.json",
        "https://getcallboard.com/api/v1/jobs?status=open&limit=100",
        "https://getcallboard.com/api/jobs?status=open&limit=100",
        "https://api.getcallboard.com/v1/jobs?status=open&limit=100",
    ],
    "agenthire": [
        "https://www.agenthire.app/skill.md",
        "https://www.agenthire.app/openapi.json",
        "https://www.agenthire.app/api/v1/jobs?status=open&limit=100",
        "https://www.agenthire.app/api/jobs?status=open&limit=100",
        "https://api.agenthire.app/v1/jobs?status=open&limit=100",
    ],
}

INVENTORY_WORDS = (
    "/jobs",
    "/tasks",
    "/bounties",
    "/gigs",
    "/opportunities",
    "/listings",
    "/marketplace",
)
BLOCKED_PATH_WORDS = (
    "/register",
    "/signup",
    "/claim",
    "/apply",
    "/bid",
    "/submit",
    "/approve",
    "/withdraw",
    "/wallet",
    "/payment",
    "/purchase",
    "/buy",
)

OUTLAY_MARKERS = (
    "registration fee",
    "listing fee",
    "application fee",
    "processing fee",
    "pay to apply",
    "pay to claim",
    "deposit required",
    "bond required",
    "stake required",
    "purchase credits",
    "buy credits",
    "fund a child bounty",
    "fully fund",
)
SOCIAL_OR_REFERRAL_MARKERS = (
    "referral",
    "refer a",
    "invite a",
    "post on x",
    "post on twitter",
    "tweet",
    "farcaster",
    "social media post",
    "promote on",
    "town square",
)
PHYSICAL_OR_IDENTITY_MARKERS = (
    "physical device",
    "record a video",
    "video proof",
    "phone number",
    "sms verification",
    "government id",
    "identity verification",
    "in-person",
)
SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|access[_-]?token|refresh[_-]?token|secret|private[_-]?key|claim[_-]?code)"
)
ABS_URL_RE = re.compile(r"https?://[^\s<>'\"`\\)\]]+")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact_url(raw: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(raw)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        clean_query = []
        for key, value in query:
            if SECRET_KEY_RE.search(key):
                value = "[REDACTED]"
            clean_query.append((key, value))
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(clean_query), "")
        )
    except Exception:
        return raw[:1000]


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            clean[key] = "[REDACTED]" if SECRET_KEY_RE.search(key) else sanitize(item)
        return clean
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\b(?:sk|pk|api|key|token)_[A-Za-z0-9_-]{16,}\b", "[REDACTED]", value)
        value = re.sub(r"\b0x[a-fA-F0-9]{64}\b", "[REDACTED_HEX]", value)
        return value[:6000]
    return value


def fetch(url: str, retries: int = 1) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/markdown,text/plain,text/html;q=0.8,*/*;q=0.2",
            "User-Agent": "nexaworks-agent-market-readonly-probe/1.0",
        },
        method="GET",
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                data = response.read(MAX_BYTES + 1)
                truncated = len(data) > MAX_BYTES
                data = data[:MAX_BYTES]
                text = data.decode("utf-8", errors="replace")
                content_type = response.headers.get("content-type", "")
                payload: Any = None
                if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = None
                return {
                    "ok": True,
                    "status": response.status,
                    "url": redact_url(response.geturl()),
                    "content_type": content_type,
                    "bytes": len(data),
                    "truncated": truncated,
                    "text": text,
                    "json": payload,
                }
        except urllib.error.HTTPError as exc:
            body = exc.read(12_000).decode("utf-8", errors="replace")
            if exc.code >= 500 and attempt < retries:
                last = exc
                time.sleep(2**attempt)
                continue
            return {
                "ok": False,
                "status": exc.code,
                "url": redact_url(url),
                "content_type": exc.headers.get("content-type", "") if exc.headers else "",
                "error_preview": sanitize(body[:2000]),
            }
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            break
    return {"ok": False, "url": redact_url(url), "error": f"{type(last).__name__}: {last}"}


def same_market_host(market: str, host: str) -> bool:
    host = host.lower().split(":", 1)[0]
    allowed = {
        "worq": ("worq.dev", "api.worq.dev"),
        "agrenting": ("agrenting.com", "api.agrenting.com"),
        "agentjob": ("agent-job.ai", "api.agent-job.ai"),
        "clawlancer": ("clawlancer.ai", "api.clawlancer.ai"),
        "callboard": ("getcallboard.com", "api.getcallboard.com"),
        "agenthire": ("agenthire.app", "api.agenthire.app"),
    }[market]
    return any(host == item or host.endswith("." + item) for item in allowed)


def is_safe_get_candidate(market: str, raw_url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except Exception:
        return False
    if parsed.scheme not in {"https", "http"} or not same_market_host(market, parsed.netloc):
        return False
    lower_path = parsed.path.lower()
    if any(word in lower_path for word in BLOCKED_PATH_WORDS):
        return False
    return any(word in lower_path for word in INVENTORY_WORDS) or lower_path.endswith(
        ("/skill.md", "/openapi.json", "/api/info", "/docs")
    )


def absolute_urls_from_text(market: str, text: str) -> set[str]:
    result: set[str] = set()
    for match in ABS_URL_RE.finditer(text):
        candidate = match.group(0).rstrip(".,;:")
        if is_safe_get_candidate(market, candidate):
            result.add(candidate)
    return result


def openapi_inventory_urls(market: str, source_url: str, payload: Any) -> set[str]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("paths"), Mapping):
        return set()
    parsed = urllib.parse.urlsplit(source_url)
    bases: list[str] = []
    servers = payload.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if isinstance(server, Mapping) and isinstance(server.get("url"), str):
                bases.append(server["url"].rstrip("/"))
    if not bases:
        bases.append(f"{parsed.scheme}://{parsed.netloc}")
    result: set[str] = set()
    for path, methods in payload["paths"].items():
        if not isinstance(path, str) or not isinstance(methods, Mapping) or "get" not in methods:
            continue
        lower = path.lower()
        if "{" in path or any(word in lower for word in BLOCKED_PATH_WORDS):
            continue
        if not any(word in lower for word in INVENTORY_WORDS):
            continue
        for base in bases:
            candidate = urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))
            if is_safe_get_candidate(market, candidate):
                result.add(candidate)
    return result


def unwrap_list(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "items", "jobs", "tasks", "bounties", "gigs", "opportunities", "listings", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
            if isinstance(candidate, Mapping):
                nested = unwrap_list(candidate)
                if nested:
                    return nested
    return []


def pick(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item.get(key) is not None:
            return item.get(key)
    return None


def numeric_amount(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"(?:\$|USDC\s*)?([0-9]+(?:\.[0-9]+)?)", value.replace(",", ""), re.I)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    if isinstance(value, Mapping):
        for key in ("usd", "usdc", "amount", "value", "budget", "reward"):
            amount = numeric_amount(value.get(key))
            if amount is not None:
                return amount
    return None


def compact_item(market: str, item: Mapping[str, Any]) -> dict[str, Any]:
    title = str(pick(item, "title", "name", "task_title", "jobTitle") or "")
    description = str(pick(item, "description", "summary", "details", "goal", "prompt") or "")
    status = str(pick(item, "status", "state", "work_state", "availability") or "")
    reward_raw = pick(
        item,
        "reward",
        "reward_amount",
        "rewardAmount",
        "budget",
        "budget_usdc",
        "budgetUsdc",
        "amount",
        "bounty",
        "bounty_cents",
        "compensation",
        "pay",
    )
    amount = numeric_amount(reward_raw)
    if isinstance(reward_raw, (int, float)) and "cents" in " ".join(item.keys()).lower():
        amount = float(reward_raw) / 100.0
    combined = f"{title}\n{description}\n{json.dumps(sanitize(item), ensure_ascii=False)}".lower()
    blockers: list[str] = []
    for marker in OUTLAY_MARKERS:
        if marker in combined:
            blockers.append(marker)
    for marker in SOCIAL_OR_REFERRAL_MARKERS:
        if marker in combined:
            blockers.append(marker)
    for marker in PHYSICAL_OR_IDENTITY_MARKERS:
        if marker in combined:
            blockers.append(marker)
    status_lower = status.lower()
    open_status = not status or any(word in status_lower for word in ("open", "active", "available", "posted", "new"))
    if any(word in status_lower for word in ("closed", "cancel", "complete", "awarded", "expired", "filled", "paid")):
        open_status = False
        blockers.append(f"status:{status_lower}")
    payment_text = str(pick(item, "payment_status", "paymentStatus", "escrow_status", "escrowStatus") or "")
    funded = bool(pick(item, "funded", "escrowed", "payment_committed", "paymentCommitted"))
    if any(word in payment_text.lower() for word in ("funded", "escrow", "secured", "paid")):
        funded = True
    actionable = open_status and not blockers and (amount is None or amount > 0)
    return {
        "market": market,
        "id": pick(item, "id", "job_id", "jobId", "task_id", "taskId", "slug"),
        "title": title[:500],
        "description": description[:2500],
        "status": status,
        "amount_hint": amount,
        "currency": pick(item, "currency", "rewardCurrency", "token", "payment_currency"),
        "deadline": pick(item, "deadline", "deadline_at", "deadlineAt", "expires_at", "expiresAt"),
        "payment_status": payment_text,
        "funded_signal": funded,
        "acceptance_criteria": sanitize(pick(item, "acceptance_criteria", "acceptanceCriteria", "criteria", "deliverables")),
        "url": redact_url(str(pick(item, "url", "public_url", "publicUrl", "job_url", "jobUrl") or "")),
        "blockers": sorted(set(blockers)),
        "actionable_without_outlay": actionable,
    }


def summarize_response(market: str, response: Mapping[str, Any]) -> dict[str, Any]:
    summary = {key: sanitize(response.get(key)) for key in ("ok", "status", "url", "content_type", "bytes", "truncated", "error", "error_preview") if response.get(key) is not None}
    payload = response.get("json")
    items = unwrap_list(payload)
    compact = [compact_item(market, item) for item in items[:100]]
    summary["item_count"] = len(items)
    summary["items"] = compact
    text = str(response.get("text") or "")
    if text:
        summary["text_preview"] = sanitize(text[:4000])
    return summary


def unique(values: Iterable[str]) -> list[str]:
    return sorted({redact_url(value) for value in values if value})


def main() -> int:
    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "safety": "GET-only public discovery; no registration, signature, bid, claim, payment, submission, or withdrawal",
        "markets": {},
    }
    all_actionable: list[dict[str, Any]] = []

    for market, seed_urls in SEEDS.items():
        fetched: dict[str, dict[str, Any]] = {}
        discovered: set[str] = set(seed_urls)
        queue = list(seed_urls)
        processed: set[str] = set()

        while queue and len(processed) < 40:
            url = queue.pop(0)
            clean_url = redact_url(url)
            if clean_url in processed:
                continue
            processed.add(clean_url)
            response = fetch(url)
            fetched[clean_url] = response
            text = str(response.get("text") or "")
            payload = response.get("json")
            for candidate in absolute_urls_from_text(market, text):
                clean = redact_url(candidate)
                if clean not in processed and clean not in discovered:
                    discovered.add(clean)
                    queue.append(candidate)
            for candidate in openapi_inventory_urls(market, url, payload):
                clean = redact_url(candidate)
                if clean not in processed and clean not in discovered:
                    discovered.add(clean)
                    queue.append(candidate)

        endpoint_summaries = [summarize_response(market, response) for _, response in sorted(fetched.items())]
        market_items: list[dict[str, Any]] = []
        for endpoint in endpoint_summaries:
            market_items.extend(endpoint.get("items", []))
        actionable = [item for item in market_items if item.get("actionable_without_outlay")]
        all_actionable.extend(actionable)
        report["markets"][market] = {
            "seed_urls": unique(seed_urls),
            "discovered_urls": unique(discovered),
            "endpoint_count": len(endpoint_summaries),
            "inventory_item_count": len(market_items),
            "actionable_count": len(actionable),
            "actionable": actionable[:50],
            "endpoints": endpoint_summaries,
        }

    report["actionable_count"] = len(all_actionable)
    report["actionable"] = all_actionable[:100]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "markets": len(SEEDS), "actionable": len(all_actionable)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
