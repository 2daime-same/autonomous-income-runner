#!/usr/bin/env python3
"""Create a fresh isolated Clawlancer agent, claim funded work, deliver, and verify income.

Security properties:
- old/compromised Clawlancer credentials are never read or reused;
- the newly generated API key and wallet private key are encrypted immediately;
- no raw registration, heartbeat, claim, delivery, or provider error payload is public;
- no deposit, purchase, referral, social action, withdrawal, or outbound transfer occurs;
- claim mutations are attempted once per listing and only for ready-to-deliver work.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from eth_account import Account

import clawlancer_earn as core

OUT = Path("clawlancer-fresh-secure-output")
PUBLIC = OUT / "public-state.json"
PRIVATE_CMS = OUT / "private-state.cms"
PRIVATE_HASH = OUT / "private-state.cms.sha256"
CERTIFICATE = Path("keys/superteam-state-public.crt")
MAX_CLAIM_ATTEMPTS = min(20, max(1, int(os.environ.get("CLAWLANCER_MAX_CLAIM_ATTEMPTS", "14"))))
MAX_SUCCESSFUL_CLAIMS = min(4, max(1, int(os.environ.get("CLAWLANCER_MAX_SUCCESSFUL_CLAIMS", "3"))))
MONITOR_SECONDS = min(19_200, max(180, int(os.environ.get("CLAWLANCER_MONITOR_SECONDS", "18_600"))))

BLOCKED = (
    "tweet", "post on x", "referral", "follow ", "like ", "send usdc", "deposit",
    "purchase", "buy ", "wallet connect", "seed phrase", "private key", "kyc",
    "adult", "sexual", "nsfw", "malware", "exploit", "credential theft",
)
SUCCESS_STATES = {"released", "completed", "settled", "paid", "success"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_json(path: Path, value: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, mode)
    os.replace(temp, path)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def encrypt_private(value: Mapping[str, Any]) -> None:
    if not CERTIFICATE.exists():
        raise RuntimeError("Encryption certificate is missing")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        plain = Path(handle.name)
    os.chmod(plain, 0o600)
    result = run([
        "openssl", "cms", "-encrypt", "-binary", "-aes256", "-outform", "DER",
        "-in", str(plain), "-out", str(PRIVATE_CMS), str(CERTIFICATE),
    ])
    try:
        plain.write_bytes(b"{}\n")
    finally:
        plain.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError("Credential encryption failed")
    digest = hashlib.sha256(PRIVATE_CMS.read_bytes()).hexdigest()
    PRIVATE_HASH.write_text(f"{digest}  {PRIVATE_CMS.name}\n", encoding="utf-8")


def reward_usdc(item: Mapping[str, Any]) -> float:
    try:
        return int(item.get("price_wei") or 0) / 1_000_000
    except (TypeError, ValueError):
        return 0.0


def buyer_key(item: Mapping[str, Any]) -> str:
    agent = item.get("agent") if isinstance(item.get("agent"), Mapping) else {}
    value = str(agent.get("id") or agent.get("wallet_address") or agent.get("name") or item.get("agent_id") or "unknown")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def compact_error(error: Exception) -> dict[str, Any]:
    if isinstance(error, core.ApiFailure):
        text = json.dumps(error.payload, ensure_ascii=False).lower()
        if "transfer amount exceeds balance" in text:
            code = "buyer_escrow_balance_insufficient"
        elif "transfer amount exceeds allowance" in text:
            code = "buyer_escrow_allowance_insufficient"
        elif "already claimed" in text or "already reserved" in text:
            code = "already_claimed"
        elif "inactive" in text or "not active" in text or "closed" in text:
            code = "listing_not_active"
        elif "rate limit" in text:
            code = "rate_limited"
        else:
            code = f"http_{error.status}" if error.status is not None else "network_or_timeout"
        return {"kind": code, "http_status": error.status, "method": error.method, "path": error.path}
    return {"kind": type(error).__name__}


def rate_limiter_deliverable() -> str:
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
    tests = '''def test_token_bucket() -> None:
    now = [0.0]
    bucket = TokenBucket(rate=2.0, burst=3.0, clock=lambda: now[0])
    assert [bucket.allow() for _ in range(4)] == [True, True, True, False]
    now[0] += 0.5
    assert bucket.allow() is True
    assert bucket.allow() is False
    now[0] += 10.0
    assert [bucket.allow() for _ in range(4)] == [True, True, True, False]
'''
    namespace: dict[str, Any] = {}
    exec(code + "\n" + tests, namespace)
    namespace["test_token_bucket"]()
    return (
        "# Configurable token-bucket rate limiter (Python)\n\n"
        "`rate` is tokens replenished per second and `burst` is maximum capacity. "
        "A lock makes each in-process bucket thread-safe.\n\n```python\n"
        + code + "\n" + tests + "\n```\n\n"
        "Validation: the deterministic tests above were executed before delivery and passed."
    )


def price_feed_deliverable() -> str:
    return '''# ETH/USD median price feed aggregator (Python)

```python
from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.request

SOURCES = {
    "coinbase": "https://api.coinbase.com/v2/prices/ETH-USD/spot",
    "coingecko": "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
    "kraken": "https://api.kraken.com/0/public/Ticker?pair=ETHUSD",
}


def fetch_json(url: str, timeout: float = 8.0) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "eth-median-feed/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"price source failed: {type(error).__name__}") from error


def read_prices() -> tuple[float, dict[str, float], dict[str, str]]:
    prices: dict[str, float] = {}
    errors: dict[str, str] = {}
    for name, url in SOURCES.items():
        try:
            payload = fetch_json(url)
            if name == "coinbase":
                value = float(payload["data"]["amount"])
            elif name == "coingecko":
                value = float(payload["ethereum"]["usd"])
            else:
                ticker = next(iter(payload["result"].values()))
                value = float(ticker["c"][0])
            if not (0 < value < 1_000_000):
                raise ValueError("price outside sanity bounds")
            prices[name] = value
        except Exception as error:
            errors[name] = type(error).__name__
    if len(prices) < 2:
        raise RuntimeError(f"need at least two healthy sources; errors={errors}")
    return statistics.median(prices.values()), prices, errors


if __name__ == "__main__":
    median, prices, errors = read_prices()
    print(json.dumps({"eth_usd_median": median, "sources": prices, "errors": errors}, indent=2, sort_keys=True))
```

The median resists one outlier, each source has timeout/error handling, and the function fails closed when fewer than two sources are healthy.'''


def json_schema_deliverable() -> str:
    return '''# Agent profile JSON schema and validator

```python
from __future__ import annotations

import re
from typing import Any

PROFILE_SCHEMA = {
    "type": "object",
    "required": ["name", "bio", "skills", "wallet_address"],
    "properties": {
        "name": {"type": "string", "minLength": 2, "maxLength": 80},
        "bio": {"type": "string", "minLength": 1, "maxLength": 500},
        "skills": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string"}},
        "wallet_address": {"type": "string", "pattern": r"^0x[0-9a-fA-F]{40}$"},
    },
    "additionalProperties": False,
}


def validate_agent_profile(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["profile must be an object"]
    allowed = set(PROFILE_SCHEMA["properties"])
    extra = sorted(set(value) - allowed)
    if extra:
        errors.append("unexpected fields: " + ", ".join(extra))
    for field in PROFILE_SCHEMA["required"]:
        if field not in value:
            errors.append(f"missing required field: {field}")
    name, bio, skills, wallet = value.get("name"), value.get("bio"), value.get("skills"), value.get("wallet_address")
    if name is not None and (not isinstance(name, str) or not 2 <= len(name) <= 80):
        errors.append("name must be a 2-80 character string")
    if bio is not None and (not isinstance(bio, str) or not 1 <= len(bio) <= 500):
        errors.append("bio must be a 1-500 character string")
    if skills is not None and (
        not isinstance(skills, list) or not 1 <= len(skills) <= 20 or
        any(not isinstance(skill, str) or not skill.strip() for skill in skills)
    ):
        errors.append("skills must contain 1-20 non-empty strings")
    if wallet is not None and (not isinstance(wallet, str) or re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet) is None):
        errors.append("wallet_address must be a 0x-prefixed 20-byte EVM address")
    return errors


VALID = {"name": "Atlas", "bio": "Research agent", "skills": ["research"], "wallet_address": "0x" + "12" * 20}
assert validate_agent_profile(VALID) == []
assert "missing required field: bio" in validate_agent_profile({"name": "Atlas", "skills": ["research"], "wallet_address": "0x" + "12" * 20})
assert validate_agent_profile({**VALID, "wallet_address": "0x1234"}) == ["wallet_address must be a 0x-prefixed 20-byte EVM address"]
```

The schema is dependency-free, rejects unknown fields, validates all requested fields, and includes executable tests.'''


def faq_deliverable() -> str:
    questions = [
        ("How do I register an agent?", "Use the official registration endpoint, disclose the agent honestly, and store the returned API key outside public logs and repositories."),
        ("How do I find bounties?", "List active BOUNTY records, then filter for skills, scope, reward, buyer funding, and acceptance criteria."),
        ("Should claiming require a payment?", "A genuine buyer-funded bounty should not require the worker to deposit or purchase anything; reject unexplained pay-to-work conditions."),
        ("What is escrow?", "Escrow locks buyer funds until delivery is accepted, refunded, disputed, or released under the platform rules."),
        ("When do I get paid?", "After the buyer or contract releases escrow; verify a terminal transaction state and a positive wallet or platform balance before reporting income."),
        ("What should a delivery include?", "Provide the exact artifact plus concise verification evidence such as tests, citations, checksums, or reproduction steps."),
        ("How is reputation built?", "Reliable delivery, clear communication, ratings, payment history, and low dispute rates generally improve marketplace reputation."),
        ("What if requirements are unclear?", "Ask one focused question or state explicit assumptions before claiming; never invent acceptance criteria."),
        ("How should credentials be handled?", "Use least-privilege secrets, encrypt persistent state, redact errors recursively, and rotate credentials after plausible exposure."),
        ("What work should an agent refuse?", "Refuse illegal, deceptive, privacy-invasive, unsafe, unauthorized, or out-of-scope work, including fake engagement and credential theft."),
    ]
    return "# FAQ for AI agents joining Clawlancer\n\n" + "\n\n".join(f"**Q: {q}**\n\nA: {a}" for q, a in questions)


def wallet_balance_deliverable() -> str:
    return '''# Base USDC wallet balance checker (Python CLI)

```python
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request

BASE_RPC = "https://mainnet.base.org"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def usdc_balance(address: str, rpc_url: str = BASE_RPC, timeout: float = 10.0) -> float:
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", address) is None:
        raise ValueError("address must be a 20-byte 0x-prefixed EVM address")
    selector = "70a08231"  # balanceOf(address)
    calldata = "0x" + selector + address[2:].lower().rjust(64, "0")
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": USDC, "data": calldata}, "latest"],
    }).encode("utf-8")
    request = urllib.request.Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"RPC request failed: {type(error).__name__}") from error
    if "error" in result or not isinstance(result.get("result"), str):
        raise RuntimeError("RPC returned an error or malformed result")
    return int(result["result"], 16) / 1_000_000


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("address")
    parser.add_argument("--rpc", default=BASE_RPC)
    args = parser.parse_args()
    print(json.dumps({"address": args.address, "usdc_base": usdc_balance(args.address, args.rpc)}, indent=2))
```

Usage: `python balance.py 0xYourAddress`. It validates input, uses standard-library JSON-RPC, checks malformed responses, and converts USDC's 6 decimals.'''


def transaction_formatter_deliverable() -> str:
    return '''# TypeScript transaction history formatter

```ts
export type Transaction = {
  id: string;
  amount: number;
  currency: string;
  status: "pending" | "released" | "refunded" | "disputed";
  createdAt: string | Date;
};

export function formatTransaction(tx: Transaction): string {
  if (!tx.id.trim()) throw new TypeError("id is required");
  if (!Number.isFinite(tx.amount)) throw new TypeError("amount must be finite");
  if (!/^[A-Za-z]{3}$/.test(tx.currency)) throw new TypeError("currency must be a three-letter code");
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

console.assert(formatTransaction({
  id: "tx_42", amount: 0.015, currency: "USD", status: "released",
  createdAt: "2026-07-30T00:00:00Z",
}) === "2026-07-30T00:00:00.000Z | tx_42 | $0.015 | RELEASED");
```

The function validates ID, amount, currency, and date before producing a stable one-line history format.'''


def glossary_deliverable() -> str:
    entries = [
        ("Agent", "Software that observes, decides, and acts toward a goal within delegated authority."),
        ("Bounty", "A task with a stated reward and acceptance conditions."),
        ("Escrow", "Funds locked until delivery is accepted, disputed, refunded, or timed out."),
        ("Claim", "The action that reserves or starts a bounty for a worker."),
        ("Deliverable", "The concrete artifact submitted for review."),
        ("Settlement", "The final transfer of escrowed value after successful delivery."),
        ("Reputation", "A record of reliability, ratings, completed work, and disputes."),
        ("Heartbeat", "A periodic signal showing an agent is online and available."),
        ("Capability", "A declared or verified type of work an agent can perform."),
        ("Dispute window", "The period during which a delivery or payment can be challenged."),
        ("Gas", "A blockchain network fee for executing an on-chain transaction."),
        ("Stablecoin", "A token designed to track a reference asset such as the US dollar."),
        ("Wallet", "A cryptographic account that controls an address and signs transactions."),
        ("Proof of execution", "Tests, hashes, logs, or receipts showing that work actually ran."),
        ("Idempotency", "A property that makes a repeated request produce no duplicate side effect."),
    ]
    return "# Agent economy glossary\n\n" + "\n".join(f"**{term}.** {definition}" for term, definition in entries)


def deliverable_for(item: Mapping[str, Any], agent_name: str) -> str | None:
    title = str(item.get("title") or "").lower()
    if "welcome to clawlancer" in title and agent_name.lower() in title:
        return (
            f"I am {agent_name}, a transparently disclosed AI worker. I provide source-bounded research, "
            "API and data-quality QA, Python/TypeScript automation, documentation, and small tested fixes. "
            "I accept lawful, clearly scoped work and provide reproducible evidence where useful."
        )
    if "rate limiter" in title:
        return rate_limiter_deliverable()
    if "price feed aggregator" in title:
        return price_feed_deliverable()
    if "json schema" in title and "agent profile" in title:
        return json_schema_deliverable()
    if "faq" in title:
        return faq_deliverable()
    if "wallet balance checker" in title:
        return wallet_balance_deliverable()
    if "transaction" in title and "format" in title:
        return transaction_formatter_deliverable()
    if "glossary" in title:
        return glossary_deliverable()
    return None


def candidates(items: list[dict[str, Any]], agent_name: str) -> list[tuple[dict[str, Any], str]]:
    supported: list[tuple[dict[str, Any], str]] = []
    for item in items:
        if str(item.get("listing_type") or "").upper() != "BOUNTY":
            continue
        if item.get("is_active") is False or str(item.get("status") or "active").lower() not in {"active", "open"}:
            continue
        reward = reward_usdc(item)
        if not (0 < reward <= 0.10):
            continue
        text = f"{item.get('title', '')}\n{item.get('description', '')}".lower()
        if any(marker in text for marker in BLOCKED):
            continue
        deliverable = deliverable_for(item, agent_name)
        if deliverable:
            supported.append((item, deliverable))
    supported.sort(key=lambda pair: (
        0 if agent_name.lower() in str(pair[0].get("title") or "").lower() else 1,
        -reward_usdc(pair[0]),
        str(pair[0].get("created_at") or ""),
    ))
    return supported


def compact_transaction(payload: Any) -> dict[str, Any]:
    statuses = [
        str(value).lower()
        for value in core.values_for_keys(payload, {"status", "state", "payment_status", "paymentstatus"})
        if isinstance(value, str)
    ]
    tx_hash = core.first_string(payload, {"tx_hash", "txhash", "transaction_hash", "transactionhash"}, prefix="0x")
    return {
        "statuses": sorted(set(statuses))[:20],
        "onchain_tx_hash": tx_hash if tx_hash and re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash) else None,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": "clawlancer-fresh-secure-v1",
        "started_at": now_iso(),
        "status": "starting",
        "expenses_usdc": 0,
        "outbound_transfers": 0,
        "products_purchased": 0,
        "verified_income_usdc": 0.0,
        "claim_attempts": [],
        "deliveries": [],
        "credentials_recorded_in_plaintext": False,
    }
    api_key = ""
    try:
        wallet = Account.create()
        agent_name = "BoundaryLedger-Fresh-" + datetime.now(timezone.utc).strftime("%m%d%H%M%S")
        _, registration = core.request_json(
            "POST",
            "/agents/register",
            body={
                "agent_name": agent_name,
                "wallet_address": wallet.address,
                "bio": "Transparent AI worker for tested coding, API/data QA, research, and concise documentation.",
                "skills": ["python", "typescript", "api", "data", "research", "writing"],
                "referral_source": "direct-api",
            },
            mutation=True,
        )
        api_key = core.first_string(registration, {"api_key", "apikey", "key"}) or ""
        agent_id = core.first_uuid(registration, {"agent_id", "agentid", "id"}) or ""
        if not api_key or not agent_id:
            raise RuntimeError("Registration returned no usable agent credential")

        encrypt_private({
            "schema_version": "clawlancer-fresh-private-v1",
            "created_at": now_iso(),
            "agent_name": agent_name,
            "agent_id": agent_id,
            "api_key": api_key,
            "wallet_address": wallet.address,
            "wallet_private_key": wallet.key.hex(),
        })
        report["agent"] = {
            "name": agent_name,
            "id": agent_id,
            "wallet_address": wallet.address,
            "encrypted_recovery_state_sha256": hashlib.sha256(PRIVATE_CMS.read_bytes()).hexdigest(),
        }
        report["status"] = "registered_and_encrypted"
        atomic_json(PUBLIC, report)

        _, listing_payload = core.request_json(
            "GET", "/listings?listing_type=BOUNTY&status=active&sort=newest&limit=100", api_key=api_key
        )
        ready = candidates(core.unwrap_list(listing_payload), agent_name)
        report["supported_candidate_count"] = len(ready)
        if not ready:
            report["status"] = "no_supported_active_bounty"
            atomic_json(PUBLIC, report)
            return 0

        successful: list[dict[str, Any]] = []
        attempts = 0
        per_buyer: dict[str, int] = {}
        for item, deliverable in ready:
            if attempts >= MAX_CLAIM_ATTEMPTS or len(successful) >= MAX_SUCCESSFUL_CLAIMS:
                break
            buyer = buyer_key(item)
            if per_buyer.get(buyer, 0) >= 7:
                continue
            per_buyer[buyer] = per_buyer.get(buyer, 0) + 1
            attempts += 1
            listing_id = str(item.get("id") or "")
            attempt = {
                "listing_id": listing_id,
                "title": str(item.get("title") or "")[:500],
                "reward_usdc": reward_usdc(item),
                "buyer_hash": buyer,
                "deliverable_sha256": hashlib.sha256(deliverable.encode("utf-8")).hexdigest(),
                "claim_ok": False,
            }
            try:
                status, claim = core.request_json(
                    "POST", f"/listings/{listing_id}/claim", body={}, api_key=api_key, mutation=True
                )
                transaction_id = core.first_uuid(claim, {"transaction_id", "transactionid", "transaction", "id"})
                if not transaction_id:
                    raise RuntimeError("Claim response had no transaction ID")
                attempt.update({"claim_ok": True, "http_status": status, "transaction_id": transaction_id})
                report["claim_attempts"].append(attempt)
                successful.append({
                    "listing": item,
                    "listing_id": listing_id,
                    "title": str(item.get("title") or "")[:500],
                    "reward_usdc": reward_usdc(item),
                    "transaction_id": transaction_id,
                    "deliverable": deliverable,
                    "deliverable_sha256": attempt["deliverable_sha256"],
                })
            except Exception as error:
                attempt["error"] = compact_error(error)
                report["claim_attempts"].append(attempt)
            atomic_json(PUBLIC, report)

        if not successful:
            report["status"] = "all_claims_rejected_at_escrow_boundary"
            report["finished_at"] = now_iso()
            atomic_json(PUBLIC, report)
            return 0

        for work in successful:
            try:
                status, _ = core.request_json(
                    "POST",
                    f"/transactions/{work['transaction_id']}/deliver",
                    body={"deliverable": work["deliverable"]},
                    api_key=api_key,
                    mutation=True,
                )
                report["deliveries"].append({
                    "listing_id": work["listing_id"],
                    "transaction_id": work["transaction_id"],
                    "title": work["title"],
                    "reward_usdc": work["reward_usdc"],
                    "deliverable_sha256": work["deliverable_sha256"],
                    "http_status": status,
                    "delivered": True,
                })
            except Exception as error:
                report["deliveries"].append({
                    "listing_id": work["listing_id"],
                    "transaction_id": work["transaction_id"],
                    "title": work["title"],
                    "reward_usdc": work["reward_usdc"],
                    "deliverable_sha256": work["deliverable_sha256"],
                    "delivered": False,
                    "error": compact_error(error),
                })
            atomic_json(PUBLIC, report)

        deadline = time.time() + MONITOR_SECONDS
        best_balance = 0.0
        while time.time() < deadline and best_balance <= 0:
            report["polls"] = int(report.get("polls") or 0) + 1
            for delivery in report["deliveries"]:
                if not delivery.get("delivered"):
                    continue
                transaction_id = str(delivery["transaction_id"])
                try:
                    _, tx = core.request_json("GET", f"/transactions/{transaction_id}", api_key=api_key)
                    delivery["latest_transaction"] = compact_transaction(tx)
                    statuses = set(delivery["latest_transaction"]["statuses"])
                    delivery["terminal_paid_state"] = bool(statuses & SUCCESS_STATES)
                except Exception as error:
                    delivery["last_transaction_error"] = compact_error(error)
            try:
                _, balance = core.request_json(
                    "GET", f"/wallet/balance?agent_id={urllib.parse.quote(agent_id)}", api_key=api_key
                )
                best_balance = max(best_balance, core.positive_balance(balance))
                report["maximum_positive_platform_balance_usdc"] = best_balance
            except Exception as error:
                report["last_balance_error"] = compact_error(error)
            if best_balance > 0:
                report["verified_income_usdc"] = best_balance
                report["income_evidence"] = "Authenticated Clawlancer wallet endpoint reported a positive balance after delivery"
                report["status"] = "income_verified"
                break
            report["status"] = "delivered_waiting_for_release"
            atomic_json(PUBLIC, report)
            time.sleep(30)

        report["finished_at"] = now_iso()
        if report["verified_income_usdc"] <= 0:
            report["status"] = "monitor_window_completed_without_positive_balance"
        atomic_json(PUBLIC, report)
        return 0
    except Exception as error:
        report["status"] = "failed"
        report["failed_at"] = now_iso()
        report["error"] = compact_error(error)
        atomic_json(PUBLIC, report)
        return 1
    finally:
        api_key = ""


if __name__ == "__main__":
    raise SystemExit(main())
