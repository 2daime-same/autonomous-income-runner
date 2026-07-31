#!/usr/bin/env python3
"""Zero-spend AgentMart seller worker.

Creates one buyer identity and store, requests owner-email verification, waits for
verification, creates a useful private download pack, publishes it at a low
price, configures an existing owner-controlled Base wallet, answers product
questions, and records verified paid sales.

No products are purchased. No funds are sent. Secrets and verification links are
stored only in CMS-encrypted state.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import mimetypes
import os
import random
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
PUBLIC_STATE = Path("agentmart-output/public-state.json")
PRIVATE_STATE = Path("agentmart-output/private-state.cms")
PRIVATE_HASH = Path("agentmart-output/private-state.cms.sha256")
CERTIFICATE = Path("keys/superteam-state-public.crt")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
MODEL = os.environ.get("AGENTMART_MODEL", "openai/gpt-4.1-mini")
RUN_ID = os.environ.get("GITHUB_RUN_ID", str(int(time.time())))
MAX_RUNTIME_MINUTES = min(345, max(20, int(os.environ.get("MAX_RUNTIME_MINUTES", "335"))))
OWNER_EMAIL = os.environ.get("AGENTMART_OWNER_EMAIL", "2daimesame@gmail.com")
PAYOUT_WALLET = os.environ.get("AGENTMART_PAYOUT_WALLET", "0x130C29B253B3079FB9ec0D141a4603579Fe5B4d8")
PRICE_USD = 0.10
PRODUCT_NAME = "Agent Bounty Verification and Safety Kit"
PRODUCT_DESCRIPTION = (
    "A practical download pack for autonomous coding agents: a bounty intake schema, "
    "funding and claimability checklist, risk scoring matrix, report template, and "
    "source-bounded decision prompt. It helps agents reject stale, unfunded, duplicate, "
    "unsafe, or unverifiable work before spending compute."
)
SECRET_KEY_RE = re.compile(
    r"(api.?key|authorization|bearer|secret|token|password|cookie|private|credential|"
    r"verification|challenge.?token|store.?key|claim|setup.?url|email)",
    re.I,
)
SECRET_PATTERNS = [
    re.compile(r"\bbak_[A-Za-z0-9._~+/=-]{8,}\b"),
    re.compile(r"\bsk_[A-Za-z0-9._~+/=-]{8,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9._-]{20,}\b"),
    re.compile(r"\b0x[0-9a-fA-F]{64}\b"),
    re.compile(r"https://[^ \"']+(?:verify|verification)[^ \"']+", re.I),
]
POSITIVE_SALE_STATUS = {"PAID", "COMPLETED", "SETTLED", "SUCCESS", "DELIVERED"}


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


def commit_evidence(message: str, include_private: bool = True) -> None:
    paths = [str(PUBLIC_STATE)]
    if include_private and PRIVATE_STATE.exists():
        paths += [str(PRIVATE_STATE), str(PRIVATE_HASH)]
    run(["git", "add", *paths])
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    if run(["git", "commit", "-m", f"{message} [skip ci]"]).returncode != 0:
        return
    for _ in range(8):
        if run(["git", "pull", "--rebase", "origin", "main"]).returncode != 0:
            run(["git", "rebase", "--abort"])
            time.sleep(2)
            continue
        if run(["git", "push", "origin", "HEAD:main"]).returncode == 0:
            return
        time.sleep(2)


def request_json(
    method: str,
    path: str,
    *,
    buyer_key: str | None = None,
    store_key: str | None = None,
    body: Mapping[str, Any] | None = None,
    retries: int = 0,
    timeout: int = 45,
) -> tuple[int, Any]:
    url = path if path.startswith("https://") else BASE + path
    headers = {
        "Accept": "application/json",
        "User-Agent": "boundaryledger-agentmart-worker/1.0",
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
            "User-Agent": "boundaryledger-agentmart-worker/1.0",
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
    values = recursive_values(value, wanted)
    numbers: list[float] = []
    for item in values:
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


def encrypt_private(value: Mapping[str, Any]) -> None:
    if not CERTIFICATE.exists():
        raise RuntimeError("Encryption certificate missing")
    PRIVATE_STATE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        plain = Path(handle.name)
    os.chmod(plain, 0o600)
    result = run([
        "openssl", "cms", "-encrypt", "-binary", "-aes256",
        "-outform", "DER", "-in", str(plain), "-out", str(PRIVATE_STATE),
        str(CERTIFICATE),
    ])
    plain.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError("AgentMart credential encryption failed")
    digest = hashlib.sha256(PRIVATE_STATE.read_bytes()).hexdigest()
    PRIVATE_HASH.write_text(f"{digest}  {PRIVATE_STATE.name}\n", encoding="utf-8")


def github_model(system: str, user: str, max_tokens: int = 5000) -> str | None:
    if not GITHUB_TOKEN:
        return None
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user[:60_000]},
        ],
        "temperature": 0.15,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    for attempt in range(4):
        req = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "boundaryledger-agentmart-worker/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
                text = payload.get("choices", [{}])[0].get("message", {}).get("content")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        except Exception:
            time.sleep(2 ** attempt)
    return None


def parse_json_object(text: str) -> dict[str, str]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    payload = json.loads(stripped)
    if not isinstance(payload, Mapping):
        raise ValueError("Product package must be an object")
    files: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", key):
            continue
        files[key] = value
    if len(files) < 4:
        raise ValueError("Product package had too few files")
    return files


def fallback_files() -> dict[str, str]:
    return {
        "README.md": """# Agent Bounty Verification and Safety Kit\n\nUse this pack before an autonomous agent commits compute to a paid task. It separates advertised reward from verified funding, checks claimability and competition, and records a reproducible go/no-go decision.\n\nContents: intake schema, checklist, risk matrix, report template, and decision prompt.\n\nAI-authored package. Verify platform rules and primary evidence before acting.\n""",
        "CHECKLIST.md": """# Pre-Work Checklist\n\n- Confirm the canonical task is open.\n- Confirm the reward source and amount from primary evidence.\n- Confirm payment is funded or escrowed, not merely promised.\n- Confirm the worker is eligible by country, identity, AI-use, and payout rules.\n- Confirm no assignee, accepted solution, or dominant competing PR exists.\n- Confirm the deliverable and acceptance tests are explicit.\n- Confirm no deposit, purchase, referral, social spam, credential disclosure, or private-key action is required.\n- Record a deadline and evidence timestamp.\n- Classify uncertainty; do not convert unknown into permission.\n""",
        "bounty-intake.schema.json": json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["task_url", "status", "reward", "funding_evidence", "acceptance_criteria", "decision"],
            "properties": {
                "task_url": {"type": "string", "format": "uri"},
                "status": {"enum": ["open", "closed", "assigned", "unknown"]},
                "reward": {"type": "object", "required": ["amount", "currency"], "properties": {"amount": {"type": "number", "minimum": 0}, "currency": {"type": "string"}}},
                "funding_evidence": {"enum": ["escrowed", "funded", "promised", "none", "unknown"]},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "competition": {"type": "object"},
                "risks": {"type": "array", "items": {"type": "string"}},
                "decision": {"enum": ["go", "clarify", "reject"]}
            }
        }, indent=2),
        "risk-matrix.csv": "signal,severity,default_action\nreward only in title,high,clarify\nrequires deposit or purchase,critical,reject\npayment escrow verified,positive,continue\nopen competing accepted solution,high,reject\nacceptance tests explicit,positive,continue\nidentity or payout rule unknown,medium,clarify\n",
        "REPORT_TEMPLATE.md": """# Bounty Due-Diligence Report\n\n## Decision\nGO / CLARIFY / REJECT\n\n## Canonical task\nURL, owner, state, timestamp.\n\n## Reward and funding\nAmount, currency, funding state, primary evidence.\n\n## Scope and acceptance\nDeliverables, tests, exclusions, deadline.\n\n## Competition and eligibility\nAssignee, PRs, attempts, AI-use and payout eligibility.\n\n## Risks and unresolved facts\nList evidence gaps explicitly.\n\n## Next reversible action\nThe smallest safe action that preserves optionality.\n""",
        "DECISION_PROMPT.md": """You are evaluating a paid task for an autonomous worker. Use only supplied primary evidence. Distinguish advertised reward, verified funding, claimability, eligibility, acceptance criteria, competition, payout path, and prohibited prerequisites. Return GO only when the task is open, funded, eligible, scoped, and free of deposit/purchase/social-spam/credential requirements. Otherwise return CLARIFY or REJECT with exact missing evidence. Never infer payment from popularity or a reward label alone.\n""",
    }


def build_product_zip() -> Path:
    prompt = {
        "product": PRODUCT_NAME,
        "audience": "AI agents and coding assistants evaluating paid bounties",
        "requirements": [
            "Return a JSON object mapping safe filenames to complete UTF-8 file contents.",
            "Include README.md, CHECKLIST.md, DECISION_PROMPT.md, REPORT_TEMPLATE.md, bounty-intake.schema.json, risk-matrix.csv, and examples.json.",
            "Make the pack self-contained, source-bounded, and useful without external services.",
            "Do not include personal information, live credentials, private URLs, unverifiable claims, or copyrighted source text.",
            "Teach agents to distinguish advertised, funded, escrowed, accepted, pending, and settled states.",
            "Include prompt-injection, social-spam, deposit, purchase, identity, payout, competition, stale-listing, and duplicate-submission checks.",
        ],
    }
    text = github_model(
        "Create a polished digital product for an AI-agent marketplace. Return only valid JSON mapping filenames to contents. Do not use Markdown fences around the outer JSON.",
        json.dumps(prompt, ensure_ascii=False),
        7000,
    )
    try:
        files = parse_json_object(text or "")
    except Exception:
        files = fallback_files()

    forbidden = re.compile(r"(2daimesame|nexaworks|@gmail\.com|bak_|sk_|private key|seed phrase\s*[:=])", re.I)
    for name, content in files.items():
        if forbidden.search(content):
            raise RuntimeError(f"Private or credential-like content found in generated product: {name}")
    if "README.md" not in files:
        raise RuntimeError("Generated product has no README.md")

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
            raise RuntimeError(f"Corrupt product archive member: {bad}")
    return output


def safe_math_answer(challenge: str) -> int | float:
    expression = challenge
    expression = expression.replace("×", "*").replace("÷", "/").replace("−", "-")
    matches = re.findall(r"[-+*/()0-9.]+", expression.replace(" ", ""))
    candidate = max(matches, key=len) if matches else ""
    if not candidate or not re.fullmatch(r"[-+*/()0-9.]+", candidate):
        raise ValueError(f"Unsupported verification challenge: {challenge!r}")
    tree = ast.parse(candidate, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Constant)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("Unsafe verification expression")
    value = eval(compile(tree, "<challenge>", "eval"), {"__builtins__": {}}, {})
    if not isinstance(value, (int, float)):
        raise ValueError("Challenge did not produce a number")
    return int(value) if float(value).is_integer() else float(value)


def choose_available_name(parameter: str, base_name: str) -> str:
    candidates = [base_name, base_name + " Labs", base_name + " " + RUN_ID[-6:]]
    for candidate in candidates:
        query = urllib.parse.urlencode({parameter: candidate})
        try:
            _, payload = request_json("GET", f"/buyer/check-name?{query}", retries=1)
        except ApiError:
            if parameter == "name":
                _, payload = request_json("GET", f"/stores/check-name?{urllib.parse.urlencode({'name': candidate})}", retries=1)
            else:
                continue
        available = payload.get("available") if isinstance(payload, Mapping) else None
        if available is True:
            return candidate
    return base_name + " " + uuid.uuid4().hex[:8]


def store_verification(slug: str) -> tuple[bool, Any]:
    try:
        _, payload = request_json("GET", f"/sellers/{urllib.parse.quote(slug)}/verification", retries=1)
    except ApiError as exc:
        return False, {"status": exc.status, "error": sanitize(exc.payload)}
    values = recursive_values(payload, {"verified", "isverified", "emailverified", "ownerverified", "status"})
    for value in values:
        if value is True or (isinstance(value, str) and value.lower() in {"verified", "active", "approved"}):
            return True, payload
    return False, payload


def sale_amount(payload: Any) -> tuple[float, list[dict[str, Any]]]:
    sales: list[dict[str, Any]] = []
    if isinstance(payload, list):
        sales = [dict(item) for item in payload if isinstance(item, Mapping)]
    elif isinstance(payload, Mapping):
        for key in ("sales", "orders", "purchases", "data", "items"):
            if isinstance(payload.get(key), list):
                sales = [dict(item) for item in payload[key] if isinstance(item, Mapping)]
                break
    total = 0.0
    positive: list[dict[str, Any]] = []
    for sale in sales:
        statuses = [str(value).upper() for value in recursive_values(sale, {"status", "paymentstatus", "state"}) if isinstance(value, str)]
        amount = first_number(sale, ["sellerAmount", "netAmount", "payoutAmount", "amount", "price", "total"])
        if amount > 100 and any(key.lower().endswith("cents") for key in sale):
            amount /= 100
        if set(statuses) & POSITIVE_SALE_STATUS and amount > 0:
            total += amount
            positive.append(sanitize({
                "id_hash": short_hash(str(sale.get("id") or sale.get("order_id") or sale.get("purchase_id") or "")),
                "statuses": statuses,
                "seller_amount": amount,
                "created_at": sale.get("created_at") or sale.get("createdAt"),
                "product_id_hash": short_hash(str(sale.get("product_id") or sale.get("productId") or "")),
            }))
    return total, positive


state: dict[str, Any] = {
    "schema_version": "agentmart-worker-v1",
    "started_at": now_iso(),
    "platform": ORIGIN,
    "model": MODEL,
    "status": "starting",
    "writes_performed": [],
    "expenses_usd": 0,
    "products_purchased": 0,
    "product_price_usd": PRICE_USD,
    "verified_income_usdc": 0.0,
    "credentials_recorded_in_plaintext": False,
    "private_product_questions_recorded": False,
}
buyer_key: str | None = None
store_key: str | None = None
buyer_id: str | None = None
store_id: str | None = None
store_slug: str | None = None
product_id: str | None = None
last_commit = 0.0
answered_questions: set[str] = set()


def persist(message: str, force: bool = False) -> None:
    global last_commit
    state["updated_at"] = now_iso()
    atomic_json(PUBLIC_STATE, sanitize(state), 0o644)
    if force or time.time() - last_commit >= 8 * 60:
        commit_evidence(message, include_private=bool(buyer_key or store_key))
        last_commit = time.time()


def save_credentials() -> None:
    if not buyer_key:
        return
    encrypt_private({
        "schema_version": "agentmart-private-v1",
        "created_at": now_iso(),
        "buyer_api_key": buyer_key,
        "store_key": store_key,
        "buyer_id": buyer_id,
        "store_id": store_id,
        "store_slug": store_slug,
        "product_id": product_id,
        "owner_email": OWNER_EMAIL,
        "payout_wallet": PAYOUT_WALLET,
    })


def answer_questions() -> None:
    if not store_key or not store_id:
        return
    try:
        query = urllib.parse.urlencode({"store_id": store_id, "answered": "false"})
        _, payload = request_json("GET", f"/questions?{query}", store_key=store_key, retries=1)
    except Exception:
        return
    questions: list[dict[str, Any]] = []
    if isinstance(payload, list):
        questions = [dict(item) for item in payload if isinstance(item, Mapping)]
    elif isinstance(payload, Mapping):
        for key in ("questions", "data", "items"):
            if isinstance(payload.get(key), list):
                questions = [dict(item) for item in payload[key] if isinstance(item, Mapping)]
                break
    for question in questions:
        question_id = str(question.get("id") or "")
        if not question_id or question_id in answered_questions:
            continue
        text = str(question.get("question") or question.get("body") or "")[:8000]
        if not text:
            continue
        answer = github_model(
            "Answer a buyer question about the Agent Bounty Verification and Safety Kit. Be accurate and concise. Do not claim unsupported features, access, or testing. AI authorship is transparent. Return only the answer.",
            text,
            500,
        ) or "The download includes the schema, checklist, risk matrix, prompt, report template, examples, and a checksum manifest. It is source-bounded and requires no external service."
        try:
            request_json(
                "POST",
                f"/questions/{urllib.parse.quote(question_id)}/answer",
                store_key=store_key,
                body={"answer": answer[:5000]},
            )
            answered_questions.add(question_id)
            state["writes_performed"].append(f"question_answer:{short_hash(question_id)}")
            persist("Answer AgentMart buyer question", True)
        except Exception:
            continue


try:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", PAYOUT_WALLET):
        raise RuntimeError("Configured payout wallet is not a valid EVM address")

    username = choose_available_name("name", "BoundaryLedger Merchant")
    agent_name = choose_available_name("agent_name", "BoundaryLedger Toolsmith")
    _, registration = request_json(
        "POST",
        "/buyer/register",
        body={
            "email": OWNER_EMAIL,
            "name": username,
            "agent_name": agent_name,
            "agent_type": "custom",
        },
        retries=1,
    )
    buyer_key = first_string(registration, ["api_key", "apiKey", "key"])
    buyer_id = first_string(registration, ["buyer_id", "buyerId", "id"])
    if not buyer_key:
        raise RuntimeError("AgentMart registration returned no buyer API key")
    state["buyer"] = {
        "id_hash": short_hash(buyer_id or ""),
        "username": username,
        "agent_name": agent_name,
    }
    state["writes_performed"].append("buyer_registration")
    save_credentials()
    persist("Register AgentMart buyer", True)

    store_name = "BoundaryLedger Toolsmith"
    try:
        _, availability = request_json("GET", "/stores/check-name?" + urllib.parse.urlencode({"name": store_name}), retries=1)
        if isinstance(availability, Mapping) and availability.get("available") is False:
            store_name += " " + RUN_ID[-6:]
    except Exception:
        store_name += " " + RUN_ID[-6:]

    _, store_response = request_json(
        "POST",
        "/stores/create",
        buyer_key=buyer_key,
        body={"name": store_name, "email": OWNER_EMAIL},
        retries=1,
    )
    store_key = first_string(store_response, ["secret_key", "secretKey", "store_key", "storeKey"])
    store_id = first_string(store_response, ["store_id", "storeId", "id"])
    store_slug = first_string(store_response, ["store_slug", "storeSlug", "slug"])
    if not store_key or not store_slug:
        raise RuntimeError("AgentMart store creation returned no secret key or slug")
    state["store"] = {
        "id_hash": short_hash(store_id or ""),
        "name": store_name,
        "slug": store_slug,
        "verification": "pending",
        "payout_wallet": PAYOUT_WALLET,
    }
    state["writes_performed"].append("store_creation")
    save_credentials()
    persist("Create AgentMart store", True)

    try:
        request_json(
            "POST",
            "/buyer/setup-owner-email",
            buyer_key=buyer_key,
            body={"email": OWNER_EMAIL},
            retries=1,
        )
        state["writes_performed"].append("owner_verification_email_request")
        state["verification_email_requested_at"] = now_iso()
    except ApiError as exc:
        if exc.status not in {400, 409}:
            raise
        state["verification_email_request_status"] = exc.status
    persist("Request AgentMart owner verification", True)

    deadline = time.time() + MAX_RUNTIME_MINUTES * 60
    verified = False
    while time.time() < deadline and not verified:
        verified, verification = store_verification(store_slug)
        state["store"]["verification"] = "verified" if verified else "pending"
        state["verification_snapshot"] = sanitize(verification)
        persist("Refresh AgentMart verification state")
        if verified:
            break
        time.sleep(15)

    if not verified:
        state["status"] = "awaiting_owner_email_verification"
        state["finished_at"] = now_iso()
        persist("Pause AgentMart worker awaiting owner verification", True)
        raise SystemExit(0)

    request_json(
        "PATCH",
        "/stores/wallet",
        store_key=store_key,
        body={"wallet_usdc": PAYOUT_WALLET},
        retries=1,
    )
    state["writes_performed"].append("payout_wallet_configuration")
    try:
        request_json(
            "POST",
            "/stores/update",
            store_key=store_key,
            body={
                "name": store_name,
                "description": "Low-cost verification kits, structured prompts, and reproducible safety workflows for autonomous agents.",
            },
        )
        state["writes_performed"].append("store_profile_update")
    except Exception:
        pass
    save_credentials()
    persist("Verify and configure AgentMart store", True)

    categories: list[str] = []
    try:
        _, category_payload = request_json("GET", "/categories", retries=1)
        if isinstance(category_payload, list):
            entries = category_payload
        elif isinstance(category_payload, Mapping):
            entries = next((category_payload[key] for key in ("categories", "data", "items") if isinstance(category_payload.get(key), list)), [])
        else:
            entries = []
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
        retries=1,
    )
    product_id = first_string(product_response, ["product_id", "productId", "id"])
    if not product_id:
        raise RuntimeError("AgentMart product creation returned no product ID")
    state["product"] = {
        "id_hash": short_hash(product_id),
        "name": PRODUCT_NAME,
        "price_usd": PRICE_USD,
        "category": category,
        "status": "draft",
    }
    state["writes_performed"].append("product_creation")
    save_credentials()
    persist("Create AgentMart product", True)

    _, challenge_response = request_json(
        "POST",
        f"/products/{urllib.parse.quote(product_id)}/publish",
        store_key=store_key,
        body={},
        retries=1,
    )
    challenge = first_string(challenge_response, ["challenge", "question"])
    challenge_token = first_string(challenge_response, ["challenge_token", "challengeToken", "token"])
    if not challenge or not challenge_token:
        raise RuntimeError("AgentMart publish did not return a verification challenge")
    answer = safe_math_answer(challenge)
    _, publish_response = request_json(
        "POST",
        f"/products/{urllib.parse.quote(product_id)}/publish",
        store_key=store_key,
        body={"challenge_token": challenge_token, "challenge_answer": answer},
        retries=1,
    )
    state["product"]["status"] = "published"
    state["product"]["public_url"] = first_string(publish_response, ["url", "product_url", "productUrl"])
    state["writes_performed"].append("product_publish")
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

    state["status"] = "published_waiting_for_paid_sale"
    persist("Start AgentMart paid-sale monitor", True)

    while time.time() < deadline and state["verified_income_usdc"] <= 0:
        state["polls"] = int(state.get("polls") or 0) + 1
        answer_questions()
        try:
            _, sales_payload = request_json("GET", "/stores/sales", store_key=store_key, retries=1)
            amount, positive_sales = sale_amount(sales_payload)
            state["sales_snapshot"] = {
                "positive_sale_count": len(positive_sales),
                "positive_sales": positive_sales[:20],
                "verified_gross_or_net_usdc": amount,
            }
            if amount > 0:
                state["verified_income_usdc"] = amount
                state["income_evidence"] = "AgentMart paid sale with positive seller amount and terminal payment status"
        except Exception as exc:
            state["sales_poll_failures"] = int(state.get("sales_poll_failures") or 0) + 1
            state["last_sales_error"] = sanitize(str(exc))
        try:
            _, analytics = request_json("GET", "/stores/analytics", store_key=store_key, retries=1)
            state["analytics_snapshot"] = sanitize(analytics)
            revenue = first_number(analytics, ["revenue", "totalRevenue", "netRevenue", "salesRevenue", "earnings"])
            if revenue > 0:
                state["verified_income_usdc"] = max(state["verified_income_usdc"], revenue)
                state["income_evidence"] = "AgentMart authenticated store analytics reported positive revenue"
        except Exception:
            pass
        state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "published_waiting_for_paid_sale"
        persist("Refresh AgentMart sale monitor")
        if state["verified_income_usdc"] > 0:
            break
        time.sleep(30)

    state["finished_at"] = now_iso()
    state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "run_window_completed_no_sale"
    persist("Finish AgentMart seller run", True)
except SystemExit:
    raise
except Exception as exc:
    state["status"] = "failed"
    state["failed_at"] = now_iso()
    if isinstance(exc, ApiError):
        state["error"] = {"message": str(exc), "status": exc.status, "payload": sanitize(exc.payload)}
    else:
        state["error"] = sanitize(f"{type(exc).__name__}: {exc}")
    persist("Record AgentMart worker failure", True)
    raise
