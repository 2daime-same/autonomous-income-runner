#!/usr/bin/env python3
"""Register, claim, verify, deliver, and monitor one zero-cost Clawlancer bounty.

Mutating requests are intentionally attempted once. The API key and wallet private
key are written only to a local private-state file; the workflow encrypts it before
any commit. Public output is recursively sanitized.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from eth_account import Account
from eth_utils import is_checksum_address

BASE = "https://clawlancer.ai/api"
OUTPUT_DIR = Path(os.environ.get("CLAWLANCER_OUTPUT_DIR", "clawlancer-output"))
STATE_FILE = Path(os.environ.get("CLAWLANCER_STATE_FILE", ".clawlancer-state/private.json"))
TIMEOUT = 45
SECRET_KEYS = {
    "api_key", "apikey", "private_key", "privatekey", "secret", "token",
    "authorization", "bearer", "mnemonic", "seed", "raw_key", "rawkey",
}
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


class ApiFailure(RuntimeError):
    def __init__(self, method: str, path: str, status: int | None, payload: Any):
        super().__init__(f"{method} {path} failed with {status}: {json.dumps(sanitize(payload), ensure_ascii=False)[:1200]}")
        self.method = method
        self.path = path
        self.status = status
        self.payload = payload


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
        value = re.sub(r"\b(?:claw|cl|api)_[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
        value = re.sub(r"\b0x[0-9a-fA-F]{64}\b", "[REDACTED_PRIVATE_KEY]", value)
    return value


def atomic_json(path: Path, value: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def request_json(
    method: str,
    path: str,
    *,
    body: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    mutation: bool = False,
) -> tuple[int, Any]:
    url = path if path.startswith("https://") else BASE + path
    headers = {
        "Accept": "application/json",
        "User-Agent": "nexaworks-clawlancer-earner/1.0",
    }
    data: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    attempts = 1 if mutation else 3
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode("utf-8", errors="replace")
                try:
                    payload: Any = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    payload = raw
                return response.status, payload
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw[:5000]
            if mutation or error.code < 500 or attempt + 1 >= attempts:
                raise ApiFailure(method, path, error.code, payload) from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if mutation or attempt + 1 >= attempts:
                raise ApiFailure(method, path, None, f"{type(error).__name__}: {error}") from error
        time.sleep(2**attempt)
    raise ApiFailure(method, path, None, f"request failed: {last_error}")


def values_for_keys(value: Any, wanted: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).replace("-", "_").lower()
            if key in wanted:
                found.append(item)
            found.extend(values_for_keys(item, wanted))
    elif isinstance(value, list):
        for item in value:
            found.extend(values_for_keys(item, wanted))
    return found


def first_string(value: Any, keys: set[str], prefix: str | None = None) -> str | None:
    for candidate in values_for_keys(value, keys):
        if isinstance(candidate, str) and (prefix is None or candidate.startswith(prefix)):
            return candidate
    return None


def first_uuid(value: Any, preferred_keys: set[str]) -> str | None:
    for candidate in values_for_keys(value, preferred_keys):
        if isinstance(candidate, str) and UUID_RE.fullmatch(candidate):
            return candidate
    return None


def unwrap_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("listings", "data", "items", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [dict(item) for item in candidate if isinstance(item, Mapping)]
    return []


def choose_listing(items: list[dict[str, Any]], agent_name: str) -> dict[str, Any] | None:
    safe: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("listing_type") or "").upper() != "BOUNTY":
            continue
        if item.get("is_active") is False or str(item.get("status") or "active").lower() not in {"active", "open"}:
            continue
        title = str(item.get("title") or "")
        description = str(item.get("description") or "")
        text = f"{title}\n{description}".lower()
        if any(marker in text for marker in ("tweet", "post on x", "referral", "send usdc", "deposit", "purchase", "buy ")):
            continue
        try:
            price = int(item.get("price_wei") or 0)
        except (TypeError, ValueError):
            continue
        if not (0 < price <= 50_000):
            continue
        safe.append(item)

    personalized = [
        item for item in safe
        if agent_name.lower() in str(item.get("title") or "").lower()
        and "welcome to clawlancer" in str(item.get("title") or "").lower()
    ]
    if personalized:
        return sorted(personalized, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]

    priorities = (
        "write a regex to validate ethereum addresses",
        "create a glossary of agent economy terms",
        "draft an faq for new ai agents",
    )
    for wanted in priorities:
        matches = [item for item in safe if str(item.get("title") or "").strip().lower() == wanted]
        if matches:
            return sorted(matches, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]
    return sorted(safe, key=lambda item: (int(item.get("price_wei") or 0), str(item.get("created_at") or "")))[0] if safe else None


def regex_deliverable() -> str:
    address_pattern = re.compile(r"^0x[0-9a-fA-F]{40}$")

    def valid(value: str) -> bool:
        if not isinstance(value, str) or address_pattern.fullmatch(value) is None:
            return False
        body = value[2:]
        if body.islower() or body.isupper():
            return True
        return is_checksum_address(value)

    cases = {
        "0xde709f2102306220921060314715629080e2fb77": True,
        "0xDE709F2102306220921060314715629080E2FB77": True,
        "0x52908400098527886E0F7030069857D2E4169EE7": True,
        "0x8617E340B3D01FA5F11F306F4090FD50E238070D": True,
        "0x52908400098527886E0F7030069857D2E4169Ee7": False,
        "52908400098527886E0F7030069857D2E4169EE7": False,
        "0x1234": False,
    }
    for value, expected in cases.items():
        actual = valid(value)
        if actual is not expected:
            raise AssertionError(f"Ethereum validation self-test failed for {value}: {actual} != {expected}")

    return '''Python implementation (format regex + EIP-55 checksum validation):

```python
import re
from eth_utils import is_checksum_address

ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

def is_valid_ethereum_address(value: str) -> bool:
    if not isinstance(value, str) or ETH_ADDRESS_RE.fullmatch(value) is None:
        return False

    body = value[2:]
    # All-lowercase and all-uppercase are accepted non-checksummed forms.
    if body.islower() or body.isupper():
        return True

    # Mixed case must satisfy EIP-55; a regex alone cannot verify Keccak casing.
    return is_checksum_address(value)
```

Tests:

```python
assert is_valid_ethereum_address("0xde709f2102306220921060314715629080e2fb77")
assert is_valid_ethereum_address("0xDE709F2102306220921060314715629080E2FB77")
assert is_valid_ethereum_address("0x52908400098527886E0F7030069857D2E4169EE7")
assert is_valid_ethereum_address("0x8617E340B3D01FA5F11F306F4090FD50E238070D")
assert not is_valid_ethereum_address("0x52908400098527886E0F7030069857D2E4169Ee7")
assert not is_valid_ethereum_address("52908400098527886E0F7030069857D2E4169EE7")
assert not is_valid_ethereum_address("0x1234")
```

Dependency: `pip install eth-utils`. I executed the same cases before submission; all passed.'''


def glossary_deliverable() -> str:
    entries = [
        ("Agent", "Software that can observe, decide, and take actions toward a goal with limited autonomy."),
        ("Bounty", "A defined task with a stated reward that is paid when its acceptance conditions are met."),
        ("Escrow", "Funds locked by a neutral mechanism until work is accepted, disputed, refunded, or timed out."),
        ("Reputation", "A portable or platform-specific record of an agent's completed work, ratings, and reliability."),
        ("Heartbeat", "A periodic signal showing that an agent is online and available to receive or continue work."),
        ("Capability", "A declared and sometimes verified type of work an agent can perform, such as research or coding."),
        ("Listing", "A marketplace record advertising a service for sale or a task available to complete."),
        ("Claim", "The action that reserves or starts a bounty for a particular worker under the marketplace rules."),
        ("Deliverable", "The concrete output submitted for review, such as code, a report, a URL, or structured data."),
        ("Settlement", "The final transfer of escrowed value after successful delivery and review."),
        ("Dispute window", "A defined period in which either party may challenge a delivery or payment outcome."),
        ("Gas", "A blockchain network fee paid to execute an on-chain transaction."),
        ("Stablecoin", "A token designed to track a reference asset such as the US dollar, for example USDC."),
        ("Wallet", "A cryptographic account that controls addresses and signs transactions or authentication messages."),
        ("Proof of execution", "Evidence that work actually ran or was completed, such as tests, hashes, logs, or transaction records."),
    ]
    return "# Agent Economy Glossary\n\n" + "\n".join(f"**{term}.** {definition}" for term, definition in entries)


def faq_deliverable() -> str:
    qa = [
        ("How do I register an agent?", "Use the official registration endpoint or MCP tool, then store the API key securely because it may be shown only once."),
        ("How do I find bounties?", "Query active BOUNTY listings and filter by scope, skills, reward, status, and buyer payment history."),
        ("Does claiming a bounty cost money?", "A genuine pre-funded bounty should be free to claim; never send funds unless the platform's official rules clearly require them."),
        ("When do I get paid?", "Payment is released after the buyer accepts the delivery or after any documented automatic-release period expires."),
        ("What is escrow?", "Escrow holds the buyer's funds until the delivery is accepted, refunded, or resolved through a dispute."),
        ("What should a delivery contain?", "Provide the requested result plus concise verification evidence such as tests, citations, checksums, or reproducible steps."),
        ("How does reputation work?", "Successful deliveries, ratings, response time, and disputes usually affect an agent's marketplace reputation."),
        ("What if requirements are unclear?", "Ask a focused question before claiming or state explicit assumptions in the delivery so the scope remains auditable."),
        ("How should API keys be stored?", "Keep them out of public repositories and logs; use a secret store or encrypt persistent state."),
        ("What work should an agent refuse?", "Refuse illegal, deceptive, privacy-invasive, unsafe, or out-of-scope tasks and anything that requires unauthorized access."),
    ]
    return "# FAQ for New AI Agents\n\n" + "\n\n".join(f"**Q: {q}**\n\nA: {a}" for q, a in qa)


def deliverable_for(listing: Mapping[str, Any], agent_name: str) -> str:
    title = str(listing.get("title") or "")
    lower = title.lower()
    if "welcome to clawlancer" in lower:
        return (
            f"Hello, I am {agent_name}, a transparent autonomous AI worker operated with its account owner's authorization. "
            "I specialize in source-backed technical research, API and data-quality QA, Python/TypeScript automation, "
            "small code fixes, documentation, and reproducible validation. I am looking for lawful, clearly scoped work "
            "with machine-checkable acceptance criteria. My deliveries include tests, citations or checksums where useful, "
            "and I disclose AI authorship rather than claiming human employment history."
        )
    if "regex" in lower and "ethereum" in lower:
        return regex_deliverable()
    if "glossary" in lower:
        return glossary_deliverable()
    if "faq" in lower:
        return faq_deliverable()
    raise RuntimeError(f"No pre-verified deliverable template for listing: {title}")


def numeric_amount(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def positive_balance(value: Any) -> float:
    candidates: list[float] = []
    for key in ("balance", "balance_usdc", "usdc_balance", "available_balance", "available", "earned", "total_earned"):
        for raw in values_for_keys(value, {key}):
            amount = numeric_amount(raw)
            if amount is not None:
                candidates.append(amount)
    return max(candidates, default=0.0)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run: dict[str, Any] = {
        "started_at": now_iso(),
        "writes_performed": [],
        "writes_not_performed": ["deposit", "purchase", "withdrawal", "social_post", "referral"],
        "income_confirmed_usdc": 0.0,
    }
    api_key: str | None = None
    try:
        wallet = Account.create()
        wallet_address = wallet.address
        wallet_private_key = wallet.key.hex()
        agent_name = "BoundaryLedger-Income-" + datetime.now(timezone.utc).strftime("%m%d%H%M%S")
        registration_body = {
            "agent_name": agent_name,
            "wallet_address": wallet_address,
            "bio": "Transparent AI worker for reproducible research, API QA, Python/TypeScript automation, and small code fixes.",
            "skills": ["research", "writing", "coding", "analysis", "data"],
            "referral_source": "direct-api",
        }
        registration_status, registration = request_json(
            "POST", "/agents/register", body=registration_body, mutation=True
        )
        api_key = first_string(registration, {"api_key", "apikey", "key"})
        agent_id = first_uuid(registration, {"agent_id", "agentid", "id"})
        if not api_key:
            raise RuntimeError(f"Registration returned no API key: {json.dumps(sanitize(registration))[:1500]}")
        if not agent_id:
            raise RuntimeError(f"Registration returned no agent UUID: {json.dumps(sanitize(registration))[:1500]}")
        run["writes_performed"].append("agent_registration")
        run["registration"] = {
            "http_status": registration_status,
            "agent_name": agent_name,
            "agent_id": agent_id,
            "wallet_address": wallet_address,
            "response": sanitize(registration),
        }
        atomic_json(
            STATE_FILE,
            {
                "platform": "clawlancer",
                "created_at": now_iso(),
                "agent_name": agent_name,
                "agent_id": agent_id,
                "api_key": api_key,
                "wallet_address": wallet_address,
                "wallet_private_key": wallet_private_key,
            },
            mode=0o600,
        )

        listing: dict[str, Any] | None = None
        listing_payload: Any = None
        for _ in range(8):
            _, listing_payload = request_json("GET", "/listings?listing_type=BOUNTY&limit=100", api_key=api_key)
            listing = choose_listing(unwrap_list(listing_payload), agent_name)
            if listing and agent_name.lower() in str(listing.get("title") or "").lower():
                break
            if listing:
                # A general verified micro-bounty is already available; avoid unnecessary waiting.
                break
            time.sleep(5)
        if not listing:
            raise RuntimeError("No zero-cost micro-bounty with a locally verifiable deliverable was available")

        deliverable = deliverable_for(listing, agent_name)
        listing_id = str(listing.get("id") or "")
        if not UUID_RE.fullmatch(listing_id):
            raise RuntimeError(f"Invalid listing ID: {listing_id!r}")
        run["selected_listing"] = {
            "id": listing_id,
            "title": listing.get("title"),
            "description": listing.get("description"),
            "category": listing.get("category"),
            "price_wei": listing.get("price_wei"),
            "currency": listing.get("currency"),
            "buyer_reputation": listing.get("buyer_reputation"),
        }
        run["deliverable_preview"] = deliverable[:1000]
        run["local_validation"] = "passed"

        claim_status, claim = request_json(
            "POST", f"/listings/{listing_id}/claim", body={}, api_key=api_key, mutation=True
        )
        run["writes_performed"].append("bounty_claim")
        transaction_id = first_uuid(claim, {"transaction_id", "transactionid", "transaction", "id"})
        if not transaction_id:
            raise RuntimeError(f"Claim returned no transaction UUID: {json.dumps(sanitize(claim))[:2000]}")
        run["claim"] = {"http_status": claim_status, "transaction_id": transaction_id, "response": sanitize(claim)}

        deliver_status, delivery = request_json(
            "POST",
            f"/transactions/{transaction_id}/deliver",
            body={"deliverable": deliverable},
            api_key=api_key,
            mutation=True,
        )
        run["writes_performed"].append("work_delivery")
        run["delivery"] = {"http_status": deliver_status, "response": sanitize(delivery)}

        snapshots: list[dict[str, Any]] = []
        best_balance = 0.0
        terminal_status = ""
        for attempt in range(25):
            snapshot: dict[str, Any] = {"checked_at": now_iso()}
            for label, path in (
                ("transaction", f"/transactions/{transaction_id}"),
                ("wallet", f"/wallet/balance?agent_id={urllib.parse.quote(agent_id)}"),
            ):
                try:
                    status, payload = request_json("GET", path, api_key=api_key)
                    snapshot[label] = {"http_status": status, "payload": sanitize(payload)}
                    if label == "wallet":
                        best_balance = max(best_balance, positive_balance(payload))
                    if label == "transaction":
                        statuses = [
                            str(value).lower()
                            for value in values_for_keys(payload, {"status", "state", "payment_status", "paymentstatus"})
                            if isinstance(value, str)
                        ]
                        terminal = next(
                            (value for value in statuses if value in {"released", "completed", "settled", "paid", "success"}),
                            "",
                        )
                        if terminal:
                            terminal_status = terminal
                except Exception as error:
                    snapshot[label] = {"error": str(error)[:1000]}
            snapshots.append(snapshot)
            if best_balance > 0 or terminal_status:
                break
            if attempt < 24:
                time.sleep(12)

        run["monitor"] = {
            "checks": len(snapshots),
            "terminal_status": terminal_status or None,
            "maximum_positive_balance_observed": best_balance,
            "snapshots": snapshots[-5:],
        }
        if best_balance > 0:
            run["income_confirmed_usdc"] = best_balance
            run["income_evidence"] = "positive platform wallet balance observed after this delivery"
        elif terminal_status:
            price_wei = numeric_amount(listing.get("price_wei")) or 0.0
            run["receivable_or_settled_gross_usdc"] = price_wei / 1_000_000
            run["income_evidence"] = f"transaction status observed as {terminal_status}; wallet balance not yet positive"

        run["completed_at"] = now_iso()
        run["ok"] = True
        atomic_json(OUTPUT_DIR / "earn-result.json", sanitize(run))
        atomic_json(
            OUTPUT_DIR / "agent-public.json",
            {
                "agent_name": agent_name,
                "agent_id": agent_id,
                "wallet_address": wallet_address,
                "transaction_id": transaction_id,
                "listing_id": listing_id,
                "generated_at": now_iso(),
            },
        )
        print(json.dumps({
            "ok": True,
            "listing": listing.get("title"),
            "transaction_id": transaction_id,
            "income_confirmed_usdc": run["income_confirmed_usdc"],
            "terminal_status": terminal_status or None,
        }))
        return 0
    except Exception as error:
        run["ok"] = False
        run["failed_at"] = now_iso()
        run["error"] = f"{type(error).__name__}: {error}"
        atomic_json(OUTPUT_DIR / "earn-result.json", sanitize(run))
        print(json.dumps({"ok": False, "error": run["error"][:1000]}), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
