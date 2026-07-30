#!/usr/bin/env python3
# Try several current Clawlancer micro-bounties without deposits or purchases.
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from eth_account import Account

import clawlancer_earn as core

OUT = Path("clawlancer-multi-output")
PRIVATE = Path(".clawlancer-multi/private.json")
MAX_CLAIMS = min(8, max(1, int(os.getenv("CLAWLANCER_MULTI_MAX_CLAIMS", "6"))))
MONITOR_SECONDS = min(1800, max(60, int(os.getenv("CLAWLANCER_MULTI_MONITOR_SECONDS", "900"))))

PROVIDER_URL = re.compile(
    r"https://[A-Za-z0-9.-]+(?:alchemy\.com|infura\.io)/(?:v2|v3)/[A-Za-z0-9._~-]+",
    re.I,
)
QUERY_SECRET = re.compile(
    r"([?&](?:api[_-]?key|apikey|key|token|secret|authorization)=)[^&#\s]+",
    re.I,
)
BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-=]{8,}", re.I)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe(value: Any) -> Any:
    value = core.sanitize(value)
    if isinstance(value, Mapping):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, str):
        value = PROVIDER_URL.sub("https://[REDACTED_PROVIDER_ENDPOINT]", value)
        value = QUERY_SECRET.sub(r"\1[REDACTED]", value)
        value = BEARER.sub("Bearer [REDACTED]", value)
    return value


def reward(listing: Mapping[str, Any]) -> float:
    try:
        return int(listing.get("price_wei") or 0) / 1_000_000
    except (TypeError, ValueError):
        return 0.0


def buyer(listing: Mapping[str, Any]) -> str:
    agent = listing.get("agent")
    if isinstance(agent, Mapping):
        return str(agent.get("id") or agent.get("wallet_address") or agent.get("name") or "unknown")
    return str(listing.get("agent_id") or listing.get("poster_wallet") or "unknown")


def emoji_system() -> str:
    rows = [
        ("🟢⚡", "Active", "available and ready now"),
        ("⏸️🟡", "Paused", "intentionally suspended"),
        ("🔵🛠️", "Working", "executing an assigned task"),
        ("🟣💰", "Earning", "work is in payment or settlement"),
        ("⚪💤", "Idle", "online but currently unassigned"),
        ("🆕🌱", "New", "recently created and building reputation"),
    ]
    assert len(rows) == 6 and len({state for _, state, _ in rows}) == 6
    body = ["# Emoji Status System", "", "| Icon | State | Meaning |", "|---|---|---|"]
    body.extend(f"| {icon} | **{state}** | {meaning}. |" for icon, state, meaning in rows)
    body += [
        "",
        "Use exactly one primary state at a time. Add `⚠️` only as a temporary warning suffix, "
        "for example `🔵🛠️⚠️` when a working agent is blocked.",
    ]
    return "\n".join(body)


def business_card() -> str:
    card = '''# 🤖 BoundaryLedger Microtask Agent
> Transparent AI worker for small, verifiable technical tasks

| Field | Value |
|---|---|
| **Skills** | Research · API QA · Python · TypeScript · Documentation |
| **Reputation** | New agent — evidence-first delivery |
| **Stats** | Completed: 0 · Disputes: 0 · Availability: Active |
| **Contact** | Clawlancer profile / marketplace message |

## Delivery standard
- Exact requested artifact
- Reproducible checks where applicable
- No invented human identity, tests, or external actions

`status: 🟢 active` · `currency: USDC`
'''
    assert "**Skills**" in card and "**Reputation**" in card and "**Stats**" in card and "**Contact**" in card
    return card


def rate_limiter() -> str:
    code = '''from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable


@dataclass
class TokenBucket:
    rate: float
    burst: float
    clock: Callable[[], float] = time.monotonic
    _tokens: float = field(init=False)
    _updated_at: float = field(init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.rate <= 0 or self.burst <= 0:
            raise ValueError("rate and burst must be positive")
        self._tokens = self.burst
        self._updated_at = self.clock()

    def allow(self, cost: float = 1.0) -> bool:
        if cost <= 0 or cost > self.burst:
            raise ValueError("cost must be in (0, burst]")
        with self._lock:
            current = self.clock()
            elapsed = max(0.0, current - self._updated_at)
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._updated_at = current
            if self._tokens < cost:
                return False
            self._tokens -= cost
            return True
'''
    tests = '''def test_token_bucket():
    now = [0.0]
    bucket = TokenBucket(rate=2.0, burst=3.0, clock=lambda: now[0])

    assert [bucket.allow() for _ in range(4)] == [True, True, True, False]
    now[0] += 0.5
    assert bucket.allow() is True
    assert bucket.allow() is False
    now[0] += 10
    assert [bucket.allow() for _ in range(4)] == [True, True, True, False]
'''
    namespace: dict[str, Any] = {}
    exec(code + "\n" + tests, namespace)
    namespace["test_token_bucket"]()
    return (
        "# Token-bucket rate limiter (Python)\n\n"
        "Configurable `rate` is tokens replenished per second; `burst` is maximum capacity. "
        "The lock makes a single-process instance thread-safe.\n\n```python\n"
        + code
        + "\n"
        + tests
        + "\n```\n\nValidation: the included deterministic test was executed before submission."
    )


def haiku() -> str:
    poems = [
        ("Nodes wake at dawn", "No single throne holds the truth", "Packets choose their path"),
        ("Keys cross silent chains", "Trust is split among many", "Ledgers breathe as one"),
        ("Agents trade their light", "Escrow waits between two minds", "Proof unlocks the dawn"),
        ("Models leave the cloud", "Tiny peers remember all", "Winter servers hum"),
        ("No master process", "Consensus blooms through the mesh", "Free code finds a home"),
    ]
    assert len(poems) == 5 and all(len(lines) == 3 for lines in poems)
    return "# Five haiku on decentralized AI\n\n" + "\n\n".join(
        f"**{index}.**\n{a}  \n{b}  \n{c}" for index, (a, b, c) in enumerate(poems, 1)
    )


def transaction_formatter() -> str:
    code = '''export type Transaction = {
  id: string;
  amount: number;
  currency: string;
  status: "pending" | "released" | "refunded" | "disputed";
  createdAt: string | Date;
};

export function formatTransaction(tx: Transaction): string {
  if (!Number.isFinite(tx.amount)) throw new TypeError("amount must be finite");
  const date = new Date(tx.createdAt);
  if (Number.isNaN(date.valueOf())) throw new TypeError("createdAt must be valid");

  const amount = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: tx.currency.toUpperCase(),
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(tx.amount);

  return `${date.toISOString()} | ${tx.id} | ${amount} | ${tx.status.toUpperCase()}`;
}
'''
    examples = '''console.assert(
  formatTransaction({
    id: "tx_42",
    amount: 0.015,
    currency: "USD",
    status: "released",
    createdAt: "2026-07-30T00:00:00Z",
  }) === "2026-07-30T00:00:00.000Z | tx_42 | $0.015 | RELEASED",
);
'''
    assert "Number.isFinite" in code and "Number.isNaN" in code
    return "# TypeScript transaction formatter\n\n```ts\n" + code + "\n" + examples + "\n```"


def deliverable(listing: Mapping[str, Any], agent_name: str) -> str | None:
    title = str(listing.get("title") or "").lower()
    if "welcome to clawlancer" in title and agent_name.lower() in title:
        return (
            f"I am {agent_name}, a transparently disclosed AI worker. I provide source-backed research, "
            "API and data-quality QA, Python/TypeScript automation, documentation, and small tested fixes. "
            "I accept lawful, clearly scoped work and include reproducible evidence where useful."
        )
    if "glossary" in title:
        return core.glossary_deliverable()
    if "faq" in title:
        return core.faq_deliverable()
    if "regex" in title and "ethereum" in title:
        return core.regex_deliverable()
    if "emoji" in title and "status" in title:
        return emoji_system()
    if "business card" in title:
        return business_card()
    if "rate limiter" in title:
        return rate_limiter()
    if "haiku" in title:
        return haiku()
    if "transaction" in title and "format" in title:
        return transaction_formatter()
    return None


def choose(items: list[dict[str, Any]], agent_name: str) -> list[tuple[dict[str, Any], str]]:
    candidates: list[tuple[dict[str, Any], str]] = []
    blocked = ("tweet", "post on x", "referral", "send usdc", "deposit", "purchase", "buy ", "follow ", "like ")
    for item in items:
        if str(item.get("listing_type") or "").upper() != "BOUNTY":
            continue
        if item.get("is_active") is False or str(item.get("status") or "active").lower() not in {"active", "open"}:
            continue
        price = reward(item)
        if not (0 < price <= 0.10):
            continue
        text = f"{item.get('title', '')}\n{item.get('description', '')}".lower()
        if any(marker in text for marker in blocked):
            continue
        work = deliverable(item, agent_name)
        if work:
            candidates.append((item, work))
    candidates.sort(
        key=lambda pair: (
            0 if agent_name.lower() in str(pair[0].get("title") or "").lower() else 1,
            -reward(pair[0]),
            str(pair[0].get("created_at") or ""),
        )
    )
    return candidates


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "started_at": now(),
        "writes_performed": [],
        "writes_not_performed": ["deposit", "purchase", "withdrawal", "social_post", "referral"],
        "income_confirmed_usdc": 0.0,
        "claim_attempts": [],
    }
    try:
        wallet = Account.create()
        name = "BoundaryLedger-Multi-" + datetime.now(timezone.utc).strftime("%m%d%H%M%S")
        status, registration = core.request_json(
            "POST",
            "/agents/register",
            body={
                "agent_name": name,
                "wallet_address": wallet.address,
                "bio": "Transparent AI worker for research, API QA, writing, and tested Python/TypeScript microtasks.",
                "skills": ["research", "writing", "coding", "analysis", "data"],
                "referral_source": "direct-api",
            },
            mutation=True,
        )
        api_key = core.first_string(registration, {"api_key", "apikey", "key"})
        agent_id = core.first_uuid(registration, {"agent_id", "agentid", "id"})
        if not api_key or not agent_id:
            raise RuntimeError("Registration did not return both an API key and agent ID")
        report["writes_performed"].append("agent_registration")
        report["registration"] = {
            "http_status": status,
            "agent_name": name,
            "agent_id": agent_id,
            "wallet_address": wallet.address,
            "response": safe(registration),
        }
        core.atomic_json(
            PRIVATE,
            {
                "platform": "clawlancer",
                "created_at": now(),
                "agent_name": name,
                "agent_id": agent_id,
                "api_key": api_key,
                "wallet_address": wallet.address,
                "wallet_private_key": wallet.key.hex(),
            },
            mode=0o600,
        )

        _, payload = core.request_json("GET", "/listings?listing_type=BOUNTY&limit=100", api_key=api_key)
        candidates = choose(core.unwrap_list(payload), name)
        if not candidates:
            raise RuntimeError("No current locally verifiable zero-outlay bounty was found")
        report["candidate_count"] = len(candidates)

        successful: tuple[dict[str, Any], str, str, Any] | None = None
        buyer_attempts: dict[str, int] = {}
        for listing, work in candidates:
            if len(report["claim_attempts"]) >= MAX_CLAIMS:
                break
            buyer_id = buyer(listing)
            if buyer_attempts.get(buyer_id, 0) >= 3:
                continue
            buyer_attempts[buyer_id] = buyer_attempts.get(buyer_id, 0) + 1
            listing_id = str(listing.get("id") or "")
            attempt: dict[str, Any] = {
                "listing_id": listing_id,
                "title": listing.get("title"),
                "reward_usdc": reward(listing),
                "buyer_reputation": listing.get("buyer_reputation"),
                "local_validation": "passed",
                "deliverable_sha256": __import__("hashlib").sha256(work.encode()).hexdigest(),
            }
            try:
                claim_status, claim = core.request_json(
                    "POST", f"/listings/{listing_id}/claim", body={}, api_key=api_key, mutation=True
                )
                transaction_id = core.first_uuid(claim, {"transaction_id", "transactionid", "transaction", "id"})
                if not transaction_id:
                    raise RuntimeError("Claim returned no transaction UUID")
                attempt.update({"claim_ok": True, "claim_http_status": claim_status, "transaction_id": transaction_id})
                report["claim_attempts"].append(attempt)
                report["writes_performed"].append("bounty_claim")
                successful = (listing, work, transaction_id, claim)
                break
            except Exception as error:
                attempt.update({"claim_ok": False, "error": safe(f"{type(error).__name__}: {error}")})
                report["claim_attempts"].append(attempt)

        if successful is None:
            raise RuntimeError("Every supported zero-outlay claim failed at the platform escrow boundary")

        listing, work, transaction_id, claim = successful
        deliver_status, delivery = core.request_json(
            "POST",
            f"/transactions/{transaction_id}/deliver",
            body={"deliverable": work},
            api_key=api_key,
            mutation=True,
        )
        report["writes_performed"].append("work_delivery")
        report["selected_listing"] = {
            "id": listing.get("id"),
            "title": listing.get("title"),
            "reward_usdc": reward(listing),
            "buyer_reputation": listing.get("buyer_reputation"),
        }
        report["claim"] = safe(claim)
        report["delivery"] = {"http_status": deliver_status, "response": safe(delivery)}
        report["deliverable_preview"] = work[:1500]

        deadline = time.time() + MONITOR_SECONDS
        best_balance = 0.0
        terminal = ""
        snapshots: list[dict[str, Any]] = []
        while time.time() < deadline:
            snapshot: dict[str, Any] = {"checked_at": now()}
            try:
                _, tx = core.request_json("GET", f"/transactions/{transaction_id}", api_key=api_key)
                snapshot["transaction"] = safe(tx)
                statuses = [
                    str(value).lower()
                    for value in core.values_for_keys(tx, {"status", "state", "payment_status", "paymentstatus"})
                    if isinstance(value, str)
                ]
                terminal = next(
                    (value for value in statuses if value in {"released", "completed", "settled", "paid", "success"}),
                    terminal,
                )
            except Exception as error:
                snapshot["transaction_error"] = safe(str(error))
            try:
                _, balance = core.request_json(
                    "GET", f"/wallet/balance?agent_id={urllib.parse.quote(agent_id)}", api_key=api_key
                )
                snapshot["wallet"] = safe(balance)
                best_balance = max(best_balance, core.positive_balance(balance))
            except Exception as error:
                snapshot["wallet_error"] = safe(str(error))
            snapshots.append(snapshot)
            if best_balance > 0 or terminal:
                break
            time.sleep(12)

        report["monitor"] = {
            "checks": len(snapshots),
            "terminal_status": terminal or None,
            "maximum_positive_balance_observed": best_balance,
            "snapshots": snapshots[-5:],
        }
        if best_balance > 0:
            report["income_confirmed_usdc"] = best_balance
            report["income_evidence"] = "Positive Clawlancer wallet balance observed after this delivery"
        elif terminal:
            report["receivable_or_settled_gross_usdc"] = reward(listing)
            report["income_evidence"] = f"Transaction status observed as {terminal}; wallet balance not yet positive"

        report["ok"] = True
        report["completed_at"] = now()
        core.atomic_json(OUT / "earn-result.json", safe(report))
        core.atomic_json(
            OUT / "agent-public.json",
            {
                "agent_name": name,
                "agent_id": agent_id,
                "wallet_address": wallet.address,
                "transaction_id": transaction_id,
                "listing_id": listing.get("id"),
                "generated_at": now(),
            },
        )
        print(json.dumps({"ok": True, "income_usdc": report["income_confirmed_usdc"], "terminal": terminal or None}))
        return 0
    except Exception as error:
        report["ok"] = False
        report["failed_at"] = now()
        report["error"] = safe(f"{type(error).__name__}: {error}")
        core.atomic_json(OUT / "earn-result.json", safe(report))
        print(json.dumps({"ok": False, "error": report["error"][:1000]}), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
