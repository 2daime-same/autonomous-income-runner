#!/usr/bin/env python3
"""Publish the existing verified AgentMart draft and monitor paid sales.

Credentials are received through a one-time CMS relay and never written to the
repository. The worker is idempotent: it reuses the existing named product,
checks publication state before and after every retry, and records only
sanitized public evidence.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

BASE = "https://agentmart.store/api"
ORIGIN = "https://agentmart.store"
CREDENTIALS_FILE = Path(os.environ.get("AGENTMART_CREDENTIALS_FILE", "/tmp/agentmart-publish-credentials.json"))
PUBLIC_STATE = Path("agentmart-output/resume-state.json")
MAX_RUNTIME_MINUTES = min(330, max(10, int(os.environ.get("MAX_RUNTIME_MINUTES", "300"))))
PRODUCT_NAME = "Agent Bounty Verification and Safety Kit"
POSITIVE_SALE_STATUS = {"PAID", "COMPLETED", "SETTLED", "SUCCESS", "DELIVERED"}
MISSING = object()

SECRET_KEY_RE = re.compile(
    r"(api.?key|authorization|bearer|secret|token|password|cookie|private|credential|"
    r"challenge.?token|store.?key|claim|setup.?url|email)", re.I
)
SECRET_PATTERNS = [
    re.compile(r"\bbak_[A-Za-z0-9._~+/=-]{8,}\b"),
    re.compile(r"\bsk_[A-Za-z0-9._~+/=-]{8,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9._-]{20,}\b"),
    re.compile(r"\b0x[0-9a-fA-F]{64}\b"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I),
]


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int | None, payload: Any):
        self.method = method
        self.path = path
        self.status = status
        self.payload = payload
        super().__init__(f"{method} {path} failed ({status})")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            result[key] = "[REDACTED]" if SECRET_KEY_RE.search(key) else sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted[:12_000]
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=os.getcwd(),
        env=os.environ,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def commit_evidence(message: str) -> None:
    if not PUBLIC_STATE.exists():
        return
    run(["git", "add", str(PUBLIC_STATE)])
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    if run(["git", "commit", "-m", f"{message} [skip ci]"]).returncode != 0:
        return
    for attempt in range(12):
        if run(["git", "pull", "--rebase", "origin", "main"]).returncode != 0:
            run(["git", "rebase", "--abort"])
            time.sleep(min(20, attempt + 2))
            continue
        if run(["git", "push", "origin", "HEAD:main"]).returncode == 0:
            return
        time.sleep(min(20, attempt + 2))


def request_json(
    method: str,
    path: str,
    *,
    store_key: str | None = None,
    body: Any = MISSING,
    timeout: int = 60,
) -> tuple[int, Any]:
    url = path if path.startswith("https://") else BASE + path
    headers = {
        "Accept": "application/json",
        "User-Agent": "boundaryledger-agentmart-publish-retry/1.0",
    }
    if store_key:
        headers["X-AgentMart-Key"] = store_key
    data = None
    if body is not MISSING:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = {"text": raw[:5000]}
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"text": raw[:5000]}
        raise ApiError(method, path, exc.code, payload) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(method, path, None, type(exc).__name__) from exc


def recursive_values(value: Any, names: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in names:
                found.append(item)
            found.extend(recursive_values(item, names))
    elif isinstance(value, list):
        for item in value:
            found.extend(recursive_values(item, names))
    return found


def first_string(value: Any, names: Iterable[str]) -> str | None:
    wanted = {re.sub(r"[^a-z0-9]", "", name.lower()) for name in names}
    for item in recursive_values(value, wanted):
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def first_number(value: Any, names: Iterable[str]) -> float:
    wanted = {re.sub(r"[^a-z0-9]", "", name.lower()) for name in names}
    numbers: list[float] = []
    for item in recursive_values(value, wanted):
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            numbers.append(float(item))
        elif isinstance(item, str):
            match = re.search(r"-?\d+(?:\.\d+)?", item.replace(",", ""))
            if match:
                try:
                    numbers.append(float(match.group(0)))
                except ValueError:
                    pass
    return max(numbers, default=0.0)


def extract_items(payload: Any, keys: Iterable[str]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def product_is_published(product: Mapping[str, Any]) -> bool:
    statuses = [
        str(value).lower()
        for value in recursive_values(product, {"status", "state", "publicationstatus"})
        if isinstance(value, str)
    ]
    flags = recursive_values(product, {"published", "ispublished", "active", "isactive"})
    return bool(set(statuses) & {"published", "active", "live"}) or any(value is True for value in flags)


def list_products(store_key: str) -> list[dict[str, Any]]:
    _, payload = request_json("GET", "/products/list", store_key=store_key, timeout=90)
    return extract_items(payload, ("products", "data", "items"))


def find_product(store_key: str, product_id: str | None = None) -> dict[str, Any] | None:
    for item in list_products(store_key):
        item_id = first_string(item, ["product_id", "productId", "id"])
        if product_id and item_id == product_id:
            return item
        if not product_id and str(item.get("name") or "").strip() == PRODUCT_NAME:
            return item
    return None


def safe_math_answer(challenge: str) -> int | float:
    expression = challenge.replace("×", "*").replace("÷", "/").replace("−", "-")
    matches = re.findall(r"[-+*/()0-9.]+", expression.replace(" ", ""))
    candidate = max(matches, key=len) if matches else ""
    if not candidate or not re.fullmatch(r"[-+*/()0-9.]+", candidate):
        raise ValueError("Unsupported publication challenge")
    tree = ast.parse(candidate, mode="eval")
    allowed = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub,
        ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Constant,
    )
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("Unsafe publication challenge")
    value = eval(compile(tree, "<challenge>", "eval"), {"__builtins__": {}}, {})
    if not isinstance(value, (int, float)):
        raise ValueError("Publication challenge was not numeric")
    return int(value) if float(value).is_integer() else float(value)


def challenge_parts(payload: Any) -> tuple[str | None, str | None]:
    return (
        first_string(payload, ["challenge", "question"]),
        first_string(payload, ["challenge_token", "challengeToken", "token"]),
    )


def wait_for_published(store_key: str, product_id: str, seconds: int = 90) -> tuple[bool, dict[str, Any] | None]:
    deadline = time.time() + seconds
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        try:
            last = find_product(store_key, product_id)
            if last and product_is_published(last):
                return True, last
        except ApiError:
            pass
        time.sleep(5)
    return False, last


def publish_product(store_key: str, product_id: str, state: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    endpoint = f"/products/{urllib.parse.quote(product_id)}/publish"
    last_product: dict[str, Any] | None = None

    for attempt in range(1, 9):
        try:
            last_product = find_product(store_key, product_id)
            if last_product and product_is_published(last_product):
                state["publication_evidence"] = "authenticated_product_list"
                return True, last_product
        except ApiError as exc:
            state["publication_status_checks_failed"] = int(state.get("publication_status_checks_failed") or 0) + 1
            state["last_publication_status_error"] = {"status": exc.status}

        state["publication_challenge_attempts"] = attempt
        request_body = MISSING if attempt % 2 else {}
        try:
            _, payload = request_json(
                "POST",
                endpoint,
                store_key=store_key,
                body=request_body,
                timeout=180,
            )
        except ApiError as exc:
            state["publication_challenge_failures"] = int(state.get("publication_challenge_failures") or 0) + 1
            state["last_publication_challenge_error"] = {
                "status": exc.status,
                "kind": "timeout_or_network" if exc.status is None else "http_error",
                "payload": sanitize(exc.payload) if exc.status is not None else None,
            }
            published, last_product = wait_for_published(store_key, product_id, 20)
            if published:
                state["publication_evidence"] = "product_became_published_after_ambiguous_challenge_response"
                return True, last_product
            time.sleep(min(30, 3 * attempt))
            continue

        challenge, token = challenge_parts(payload)
        if not challenge or not token:
            published, last_product = wait_for_published(store_key, product_id, 30)
            if published:
                state["publication_evidence"] = "publication_endpoint_and_authenticated_product_list"
                return True, last_product
            state["last_challenge_shape"] = sanitize(payload)
            time.sleep(min(20, 2 * attempt))
            continue

        answer = safe_math_answer(challenge)
        state["publication_challenge_solved"] = True
        for answer_attempt in range(1, 5):
            try:
                _, result = request_json(
                    "POST",
                    endpoint,
                    store_key=store_key,
                    body={"challenge_token": token, "challenge_answer": answer},
                    timeout=180,
                )
                published, last_product = wait_for_published(store_key, product_id, 60)
                if published:
                    state["publication_evidence"] = "challenge_answer_and_authenticated_product_list"
                    return True, last_product
                status = first_string(result, ["status", "state"])
                if status and status.lower() in {"published", "active", "live"}:
                    state["publication_evidence"] = "publication_endpoint_terminal_status"
                    return True, last_product
                state["last_publish_result_shape"] = sanitize(result)
            except ApiError as exc:
                state["publication_answer_failures"] = int(state.get("publication_answer_failures") or 0) + 1
                state["last_publication_answer_error"] = {
                    "status": exc.status,
                    "kind": "timeout_or_network" if exc.status is None else "http_error",
                    "payload": sanitize(exc.payload) if exc.status is not None else None,
                }
                published, last_product = wait_for_published(store_key, product_id, 25)
                if published:
                    state["publication_evidence"] = "product_became_published_after_ambiguous_answer_response"
                    return True, last_product
            time.sleep(min(30, 4 * answer_attempt))

    published, last_product = wait_for_published(store_key, product_id, 30)
    return published, last_product


def sale_amount(payload: Any) -> tuple[float, list[dict[str, Any]]]:
    sales = extract_items(payload, ("sales", "orders", "purchases", "data", "items"))
    total = 0.0
    positive: list[dict[str, Any]] = []
    for sale in sales:
        statuses = [
            str(value).upper()
            for value in recursive_values(sale, {"status", "paymentstatus", "state"})
            if isinstance(value, str)
        ]
        amount = first_number(sale, ["sellerAmount", "netAmount", "payoutAmount", "amount", "price", "total"])
        if set(statuses) & POSITIVE_SALE_STATUS and amount > 0:
            total += amount
            positive.append({
                "id_hash": short_hash(str(sale.get("id") or sale.get("order_id") or sale.get("purchase_id") or "")),
                "statuses": statuses,
                "seller_amount": amount,
                "created_at": sale.get("created_at") or sale.get("createdAt"),
            })
    return total, positive


state: dict[str, Any] = {
    "schema_version": "agentmart-resume-v1",
    "started_at": now_iso(),
    "platform": ORIGIN,
    "status": "publication_retry_starting",
    "writes_performed": [],
    "expenses_usd": 0,
    "verified_income_usdc": 0.0,
    "credentials_recorded_in_plaintext": False,
}
last_commit = 0.0


def load_previous_state() -> None:
    if not PUBLIC_STATE.exists():
        return
    try:
        previous = json.loads(PUBLIC_STATE.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(previous, Mapping):
        return
    for key in (
        "store", "product", "product_package", "product_price_usd",
        "verification_evidence", "store_profile_update_status",
    ):
        if key in previous:
            state[key] = previous[key]
    previous_writes = previous.get("writes_performed")
    if isinstance(previous_writes, list):
        state["writes_performed"] = list(previous_writes)
    previous_income = previous.get("verified_income_usdc")
    if isinstance(previous_income, (int, float)):
        state["verified_income_usdc"] = float(previous_income)


def persist(message: str, force: bool = False) -> None:
    global last_commit
    state["updated_at"] = now_iso()
    atomic_json(PUBLIC_STATE, sanitize(state))
    if force or time.time() - last_commit >= 8 * 60:
        commit_evidence(message)
        last_commit = time.time()


def main() -> int:
    load_previous_state()
    if not CREDENTIALS_FILE.exists():
        raise RuntimeError("One-time AgentMart credential file is missing")
    os.chmod(CREDENTIALS_FILE, 0o600)
    credentials = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    CREDENTIALS_FILE.write_text("{}\n", encoding="utf-8")
    CREDENTIALS_FILE.unlink(missing_ok=True)

    store_key = str(credentials.get("store_key") or "")
    store_slug = str(credentials.get("store_slug") or "")
    store_id = str(credentials.get("store_id") or "")
    payout_wallet = str(credentials.get("payout_wallet") or "")
    if not re.fullmatch(r"sk_[A-Za-z0-9._~+/=-]{8,}", store_key):
        raise RuntimeError("Invalid store key in one-time credential file")
    if not re.fullmatch(r"[a-z0-9-]{3,100}", store_slug):
        raise RuntimeError("Invalid store slug in one-time credential file")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", payout_wallet):
        raise RuntimeError("Invalid payout wallet in one-time credential file")

    state["store"] = {
        "slug": store_slug,
        "id_hash": short_hash(store_id),
        "payout_wallet": payout_wallet,
    }
    persist("Start AgentMart publication retry", True)

    product = find_product(store_key)
    if not product:
        raise RuntimeError("Existing AgentMart product was not found; refusing to create a duplicate")
    product_id = first_string(product, ["product_id", "productId", "id"])
    if not product_id:
        raise RuntimeError("Existing AgentMart product has no ID")
    product_url = first_string(product, ["url", "product_url", "productUrl"])
    state["product"] = {
        "id_hash": short_hash(product_id),
        "name": PRODUCT_NAME,
        "price_usd": first_number(product, ["price", "amount"]),
        "public_url": product_url,
        "status": "published" if product_is_published(product) else "draft",
    }
    state["status"] = "publication_retry_in_progress"
    persist("Locate existing AgentMart draft", True)

    published, refreshed = publish_product(store_key, product_id, state)
    if not published:
        state["status"] = "publication_retry_exhausted"
        persist("Record exhausted AgentMart publication retry", True)
        return 2

    if refreshed:
        product_url = first_string(refreshed, ["url", "product_url", "productUrl"]) or product_url
    state["product"]["status"] = "published"
    state["product"]["public_url"] = product_url
    if "product_publish" not in state["writes_performed"]:
        state["writes_performed"].append("product_publish")
    state["status"] = "published_waiting_for_paid_sale"
    persist("Confirm AgentMart product publication", True)

    try:
        request_json(
            "POST",
            "/seller-updates",
            store_key=store_key,
            body={
                "title": "New low-cost bounty verification kit",
                "content": "A compact source-bounded pack for checking funding, claimability, competition, payout, and safety before an agent starts paid work.",
                "status": "published",
            },
            timeout=90,
        )
        if "seller_update" not in state["writes_performed"]:
            state["writes_performed"].append("seller_update")
    except ApiError as exc:
        state["seller_update_status"] = exc.status

    deadline = time.time() + MAX_RUNTIME_MINUTES * 60
    while time.time() < deadline and state["verified_income_usdc"] <= 0:
        state["polls"] = int(state.get("polls") or 0) + 1
        try:
            _, sales_payload = request_json("GET", "/stores/sales", store_key=store_key, timeout=90)
            amount, positive_sales = sale_amount(sales_payload)
            state["sales_snapshot"] = {
                "positive_sale_count": len(positive_sales),
                "positive_sales": positive_sales[:20],
                "verified_gross_or_net_usdc": amount,
            }
            if amount > 0:
                state["verified_income_usdc"] = amount
                state["income_evidence"] = "Authenticated AgentMart sales reported a positive terminal payment"
        except ApiError as exc:
            state["sales_poll_failures"] = int(state.get("sales_poll_failures") or 0) + 1
            state["last_sales_error"] = {"status": exc.status}
        try:
            _, analytics = request_json("GET", "/stores/analytics", store_key=store_key, timeout=90)
            revenue = first_number(analytics, ["revenue", "totalRevenue", "netRevenue", "salesRevenue", "earnings"])
            state["analytics_snapshot"] = sanitize(analytics)
            if revenue > 0:
                state["verified_income_usdc"] = max(state["verified_income_usdc"], revenue)
                state["income_evidence"] = "Authenticated AgentMart analytics reported positive revenue"
        except ApiError:
            pass
        state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "published_waiting_for_paid_sale"
        persist("Refresh AgentMart paid-sale monitor")
        if state["verified_income_usdc"] > 0:
            break
        time.sleep(30)

    state["finished_at"] = now_iso()
    state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "run_window_completed_no_sale"
    persist("Finish AgentMart publication retry and sale monitor", True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        state["status"] = "failed"
        state["failed_at"] = now_iso()
        if isinstance(exc, ApiError):
            state["error"] = {
                "message": str(exc),
                "status": exc.status,
                "payload": sanitize(exc.payload) if exc.status is not None else None,
            }
        else:
            state["error"] = sanitize(f"{type(exc).__name__}: {exc}")
        persist("Record AgentMart publication retry failure", True)
        raise
