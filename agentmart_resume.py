#!/usr/bin/env python3
"""Resume an already-verified AgentMart store from a one-time decrypted credential file.

The credential file is supplied by a relay workflow, remains outside the repository,
and is deleted after loading. Only sanitized public state is committed.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

BASE = "https://agentmart.store/api"
ORIGIN = "https://agentmart.store"
CREDENTIALS_FILE = Path(os.environ.get("AGENTMART_CREDENTIALS_FILE", "/tmp/agentmart-resume-credentials.json"))
PUBLIC_STATE = Path("agentmart-output/resume-state.json")
MAX_RUNTIME_MINUTES = min(330, max(20, int(os.environ.get("MAX_RUNTIME_MINUTES", "300"))))
PRICE_USD = 0.10
PRODUCT_NAME = "Agent Bounty Verification and Safety Kit"
PRODUCT_DESCRIPTION = (
    "A practical download pack for autonomous coding agents: a bounty intake schema, "
    "funding and claimability checklist, risk scoring matrix, report template, and "
    "source-bounded decision prompt. It helps agents reject stale, unfunded, duplicate, "
    "unsafe, or unverifiable work before spending compute."
)
POSITIVE_SALE_STATUS = {"PAID", "COMPLETED", "SETTLED", "SUCCESS", "DELIVERED"}
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
    for attempt in range(10):
        if run(["git", "pull", "--rebase", "origin", "main"]).returncode != 0:
            run(["git", "rebase", "--abort"])
            time.sleep(min(20, 2 + attempt))
            continue
        if run(["git", "push", "origin", "HEAD:main"]).returncode == 0:
            return
        time.sleep(min(20, 2 + attempt))


def request_json(
    method: str,
    path: str,
    *,
    buyer_key: str | None = None,
    store_key: str | None = None,
    body: Mapping[str, Any] | None = None,
    retries: int = 1,
    timeout: int = 45,
) -> tuple[int, Any]:
    url = path if path.startswith("https://") else BASE + path
    headers = {
        "Accept": "application/json",
        "User-Agent": "boundaryledger-agentmart-resume/1.0",
    }
    if buyer_key:
        headers["X-API-Key"] = buyer_key
    if store_key:
        headers["X-AgentMart-Key"] = store_key
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
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
            error = ApiError(method, path, exc.code, payload)
            if exc.code < 500 or attempt >= retries:
                raise error from exc
            last_error = error
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                raise ApiError(method, path, None, str(exc)) from exc
        time.sleep(min(20, 2 ** attempt))
    raise ApiError(method, path, None, str(last_error))


def upload_file(path: Path, store_key: str) -> Any:
    boundary = "----BoundaryLedger" + uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode())
    body.write(f"Content-Type: {mime}\r\n\r\n".encode())
    body.write(path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        BASE + "/upload",
        data=body.getvalue(),
        headers={
            "Accept": "application/json",
            "X-AgentMart-Key": store_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "boundaryledger-agentmart-resume/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"text": raw[:5000]}
        raise ApiError("POST", "/upload", exc.code, payload) from exc


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


def is_human_verified(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        summary = payload.get("summary")
        if isinstance(summary, Mapping):
            badges = summary.get("badges")
            if isinstance(badges, Mapping) and badges.get("human") is True:
                return True
    wanted = {
        "verified", "isverified", "emailverified", "ownerverified",
        "owneremailverified", "humanverified", "status",
    }
    for value in recursive_values(payload, wanted):
        if value is True:
            return True
        if isinstance(value, str) and value.lower() in {"verified", "active", "approved"}:
            return True
    return False


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


def build_product_zip() -> Path:
    files = {
        "README.md": """# Agent Bounty Verification and Safety Kit

Use this pack before an autonomous agent commits compute to paid work. It separates advertised reward from verified funding, checks claimability and competition, and records a reproducible go/no-go decision.

Contents: intake schema, checklist, risk matrix, report template, examples, and decision prompt. AI-authored package. Verify platform rules and primary evidence before acting.
""",
        "CHECKLIST.md": """# Pre-Work Checklist

- Confirm the canonical task is open.
- Confirm reward amount and currency from primary evidence.
- Confirm payment is funded or escrowed, not merely promised.
- Confirm eligibility by country, identity, AI-use, and payout rules.
- Confirm no assignee, accepted solution, or dominant competing PR exists.
- Confirm deliverables and acceptance tests are explicit.
- Reject tasks requiring deposits, purchases, referral spam, credential disclosure, or private-key actions.
- Record deadline, evidence timestamp, and unresolved uncertainty.
""",
        "DECISION_PROMPT.md": """Evaluate a paid task using only supplied primary evidence. Distinguish advertised reward, verified funding, claimability, eligibility, acceptance criteria, competition, payout path, and prohibited prerequisites. Return GO only when the task is open, funded, eligible, scoped, and free of deposit, purchase, social-spam, or credential requirements. Otherwise return CLARIFY or REJECT with the exact missing evidence. Never infer payment from popularity or a reward label alone.
""",
        "REPORT_TEMPLATE.md": """# Bounty Due-Diligence Report

## Decision
GO / CLARIFY / REJECT

## Canonical task
URL, owner, state, timestamp.

## Reward and funding
Amount, currency, funding state, primary evidence.

## Scope and acceptance
Deliverables, tests, exclusions, deadline.

## Competition and eligibility
Assignee, PRs, attempts, AI-use and payout eligibility.

## Risks and unresolved facts
List evidence gaps explicitly.

## Next reversible action
The smallest safe action that preserves optionality.
""",
        "bounty-intake.schema.json": json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["task_url", "status", "reward", "funding_evidence", "acceptance_criteria", "decision"],
            "properties": {
                "task_url": {"type": "string", "format": "uri"},
                "status": {"enum": ["open", "closed", "assigned", "unknown"]},
                "reward": {
                    "type": "object",
                    "required": ["amount", "currency"],
                    "properties": {
                        "amount": {"type": "number", "minimum": 0},
                        "currency": {"type": "string"},
                    },
                },
                "funding_evidence": {"enum": ["escrowed", "funded", "promised", "none", "unknown"]},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "competition": {"type": "object"},
                "risks": {"type": "array", "items": {"type": "string"}},
                "decision": {"enum": ["go", "clarify", "reject"]},
            },
        }, indent=2),
        "risk-matrix.csv": "signal,severity,default_action\nreward only in title,high,clarify\nrequires deposit or purchase,critical,reject\npayment escrow verified,positive,continue\nopen competing accepted solution,high,reject\nacceptance tests explicit,positive,continue\nidentity or payout rule unknown,medium,clarify\n",
        "examples.json": json.dumps({
            "funded_and_clear": {"funding": "escrowed", "competition": "none", "decision": "go"},
            "promised_only": {"funding": "promised", "competition": "unknown", "decision": "clarify"},
            "deposit_required": {"funding": "unknown", "prerequisite": "deposit", "decision": "reject"},
        }, indent=2),
    }
    output = Path(tempfile.gettempdir()) / "agent-bounty-verification-safety-kit.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.writestr(name, files[name].rstrip() + "\n")
        manifest = {
            "product": PRODUCT_NAME,
            "generated_at": now_iso(),
            "files": {
                name: hashlib.sha256((files[name].rstrip() + "\n").encode("utf-8")).hexdigest()
                for name in sorted(files)
            },
            "ai_authorship_disclosed": True,
        }
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Corrupt archive member: {bad}")
    return output


def product_is_published(product: Mapping[str, Any]) -> bool:
    statuses = [
        str(value).lower()
        for value in recursive_values(product, {"status", "state", "publicationstatus"})
        if isinstance(value, str)
    ]
    flags = recursive_values(product, {"published", "ispublished", "active", "isactive"})
    return bool(set(statuses) & {"published", "active", "live"}) or any(value is True for value in flags)


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
    "status": "starting",
    "writes_performed": [],
    "expenses_usd": 0,
    "product_price_usd": PRICE_USD,
    "verified_income_usdc": 0.0,
    "credentials_recorded_in_plaintext": False,
}
last_commit = 0.0


def persist(message: str, force: bool = False) -> None:
    global last_commit
    state["updated_at"] = now_iso()
    atomic_json(PUBLIC_STATE, sanitize(state))
    if force or time.time() - last_commit >= 8 * 60:
        commit_evidence(message)
        last_commit = time.time()


def main() -> int:
    if not CREDENTIALS_FILE.exists():
        raise RuntimeError("One-time AgentMart credential file is missing")
    os.chmod(CREDENTIALS_FILE, 0o600)
    credentials = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    CREDENTIALS_FILE.write_text("{}\n", encoding="utf-8")
    CREDENTIALS_FILE.unlink(missing_ok=True)

    buyer_key = str(credentials.get("buyer_api_key") or "")
    store_key = str(credentials.get("store_key") or "")
    store_slug = str(credentials.get("store_slug") or "")
    store_id = str(credentials.get("store_id") or "")
    payout_wallet = str(credentials.get("payout_wallet") or "")
    if not re.fullmatch(r"bak_[A-Za-z0-9._~+/=-]{8,}", buyer_key):
        raise RuntimeError("Invalid buyer key in one-time credential file")
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
    persist("Start secure AgentMart store resume", True)

    _, verification = request_json("GET", f"/sellers/{urllib.parse.quote(store_slug)}/verification")
    human_verified = is_human_verified(verification)
    state["verification_evidence"] = {
        "human_owner_verified": human_verified,
        "seller_badge": bool(
            isinstance(verification, Mapping)
            and isinstance(verification.get("summary"), Mapping)
            and isinstance(verification["summary"].get("badges"), Mapping)
            and verification["summary"]["badges"].get("seller") is True
        ),
    }
    if not human_verified:
        state["status"] = "owner_verification_not_visible"
        persist("Record missing AgentMart owner verification", True)
        return 2

    request_json(
        "PATCH",
        "/stores/wallet",
        store_key=store_key,
        body={"wallet_usdc": payout_wallet},
    )
    state["writes_performed"].append("payout_wallet_configuration")
    try:
        request_json(
            "POST",
            "/stores/update",
            store_key=store_key,
            body={
                "name": "BoundaryLedger Toolsmith",
                "description": "Low-cost verification kits, structured prompts, and reproducible safety workflows for autonomous agents.",
            },
        )
        state["writes_performed"].append("store_profile_update")
    except ApiError as exc:
        state["store_profile_update_status"] = exc.status
    state["status"] = "verified_configured"
    persist("Configure verified AgentMart store", True)

    products_payload: Any = None
    try:
        _, products_payload = request_json("GET", "/products/list", store_key=store_key)
    except ApiError:
        products_payload = None
    products = extract_items(products_payload, ("products", "data", "items"))
    existing = next((item for item in products if str(item.get("name") or "").strip() == PRODUCT_NAME), None)

    product_id: str | None = None
    published = False
    product_url: str | None = None
    if existing:
        product_id = first_string(existing, ["product_id", "productId", "id"])
        published = product_is_published(existing)
        product_url = first_string(existing, ["url", "product_url", "productUrl"])
        state["writes_performed"].append("existing_product_reuse")
    else:
        categories: list[str] = []
        try:
            _, category_payload = request_json("GET", "/categories")
            entries = category_payload if isinstance(category_payload, list) else extract_items(category_payload, ("categories", "data", "items"))
            for item in entries:
                if isinstance(item, str):
                    categories.append(item)
                elif isinstance(item, Mapping):
                    value = item.get("slug") or item.get("name") or item.get("id")
                    if isinstance(value, str):
                        categories.append(value)
        except Exception:
            pass
        category = next((value for value in categories if "template" in value.lower()), None)
        category = category or next((value for value in categories if "software" in value.lower()), None)
        category = category or next((value for value in categories if "guide" in value.lower()), None)
        category = category or "templates"

        package = build_product_zip()
        package_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
        upload = upload_file(package, store_key)
        file_url = first_string(upload, ["file_url", "fileUrl", "url", "download_url", "downloadUrl"])
        if not file_url:
            raise RuntimeError("AgentMart upload returned no file URL")
        state["product_package"] = {
            "filename": package.name,
            "sha256": package_sha256,
            "bytes": package.stat().st_size,
        }
        state["writes_performed"].append("product_upload")

        _, product_response = request_json(
            "POST",
            "/products/create",
            store_key=store_key,
            body={
                "name": PRODUCT_NAME,
                "price": PRICE_USD,
                "description": PRODUCT_DESCRIPTION,
                "type": "download",
                "file_url": file_url,
                "category": category,
                "tags": ["agent-safety", "bounty", "github", "due-diligence", "workflow"],
            },
        )
        product_id = first_string(product_response, ["product_id", "productId", "id"])
        if not product_id:
            raise RuntimeError("AgentMart product creation returned no product ID")
        product_url = first_string(product_response, ["url", "product_url", "productUrl"])
        state["writes_performed"].append("product_creation")

    if not product_id:
        raise RuntimeError("No AgentMart product ID available")
    state["product"] = {
        "id_hash": short_hash(product_id),
        "name": PRODUCT_NAME,
        "price_usd": PRICE_USD,
        "status": "published" if published else "draft",
        "public_url": product_url,
    }
    persist("Prepare AgentMart product", True)

    if not published:
        try:
            _, challenge_response = request_json(
                "POST",
                f"/products/{urllib.parse.quote(product_id)}/publish",
                store_key=store_key,
                body=None,
            )
            challenge = first_string(challenge_response, ["challenge", "question"])
            challenge_token = first_string(challenge_response, ["challenge_token", "challengeToken", "token"])
            if challenge and challenge_token:
                answer = safe_math_answer(challenge)
                _, publish_response = request_json(
                    "POST",
                    f"/products/{urllib.parse.quote(product_id)}/publish",
                    store_key=store_key,
                    body={"challenge_token": challenge_token, "challenge_answer": answer},
                )
                product_url = first_string(publish_response, ["url", "product_url", "productUrl"]) or product_url
                published = True
            else:
                published = bool(first_string(challenge_response, ["status"]) in {"published", "active", "live"})
        except ApiError as exc:
            if exc.status not in {400, 409}:
                raise
            _, products_payload = request_json("GET", "/products/list", store_key=store_key)
            products = extract_items(products_payload, ("products", "data", "items"))
            refreshed = next((item for item in products if first_string(item, ["product_id", "productId", "id"]) == product_id), None)
            published = bool(refreshed and product_is_published(refreshed))
            if not published:
                raise
    if not published:
        raise RuntimeError("AgentMart product did not reach published state")

    state["product"]["status"] = "published"
    state["product"]["public_url"] = product_url
    state["writes_performed"].append("product_publish")
    state["status"] = "published_waiting_for_paid_sale"
    persist("Publish AgentMart product", True)

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
        )
        state["writes_performed"].append("seller_update")
    except Exception:
        pass

    deadline = time.time() + MAX_RUNTIME_MINUTES * 60
    while time.time() < deadline and state["verified_income_usdc"] <= 0:
        state["polls"] = int(state.get("polls") or 0) + 1
        try:
            _, sales_payload = request_json("GET", "/stores/sales", store_key=store_key)
            amount, positive_sales = sale_amount(sales_payload)
            state["sales_snapshot"] = {
                "positive_sale_count": len(positive_sales),
                "positive_sales": positive_sales[:20],
                "verified_gross_or_net_usdc": amount,
            }
            if amount > 0:
                state["verified_income_usdc"] = amount
                state["income_evidence"] = "Authenticated AgentMart sales reported a positive terminal payment"
        except Exception as exc:
            state["sales_poll_failures"] = int(state.get("sales_poll_failures") or 0) + 1
            state["last_sales_error"] = sanitize(str(exc))
        try:
            _, analytics = request_json("GET", "/stores/analytics", store_key=store_key)
            revenue = first_number(analytics, ["revenue", "totalRevenue", "netRevenue", "salesRevenue", "earnings"])
            state["analytics_snapshot"] = sanitize(analytics)
            if revenue > 0:
                state["verified_income_usdc"] = max(state["verified_income_usdc"], revenue)
                state["income_evidence"] = "Authenticated AgentMart analytics reported positive revenue"
        except Exception:
            pass
        state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "published_waiting_for_paid_sale"
        persist("Refresh AgentMart resumed sale monitor")
        if state["verified_income_usdc"] > 0:
            break
        time.sleep(30)

    state["finished_at"] = now_iso()
    state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "run_window_completed_no_sale"
    persist("Finish AgentMart resumed seller run", True)
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
            state["error"] = {"message": str(exc), "status": exc.status, "payload": sanitize(exc.payload)}
        else:
            state["error"] = sanitize(f"{type(exc).__name__}: {exc}")
        persist("Record AgentMart resume failure", True)
        raise
