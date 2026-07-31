#!/usr/bin/env python3
"""Publish a diversified, zero-spend AgentMart product portfolio and monitor sales.

The worker receives an existing AgentMart store credential through a one-time
CMS relay. It never writes credentials to the repository, never buys products,
and never transfers funds. Product creation is idempotent by exact product name.
"""
from __future__ import annotations

import ast
import csv
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
CREDENTIALS_FILE = Path(os.environ.get("AGENTMART_CREDENTIALS_FILE", "/tmp/agentmart-portfolio-credentials.json"))
PUBLIC_STATE = Path("agentmart-output/portfolio-state.json")
MAX_RUNTIME_MINUTES = min(330, max(20, int(os.environ.get("MAX_RUNTIME_MINUTES", "300"))))
MISSING = object()
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


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:90] or "product"


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
    timeout: int = 90,
    attempts: int = 3,
) -> tuple[int, Any]:
    url = path if path.startswith("https://") else BASE + path
    headers = {
        "Accept": "application/json",
        "User-Agent": "boundaryledger-agentmart-portfolio/1.0",
    }
    if store_key:
        headers["X-AgentMart-Key"] = store_key
    data = None
    if body is not MISSING:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    last: ApiError | None = None
    for attempt in range(1, attempts + 1):
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
            last = ApiError(method, path, exc.code, payload)
            if exc.code < 500 or attempt >= attempts:
                raise last from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = ApiError(method, path, None, type(exc).__name__)
            if attempt >= attempts:
                raise last from exc
        time.sleep(min(20, 2 ** attempt))
    raise last or ApiError(method, path, None, "unknown")


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
            "User-Agent": "boundaryledger-agentmart-portfolio/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
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


def product_is_published(product: Mapping[str, Any]) -> bool:
    statuses = [
        str(value).lower()
        for value in recursive_values(product, {"status", "state", "publicationstatus"})
        if isinstance(value, str)
    ]
    flags = recursive_values(product, {"published", "ispublished", "active", "isactive"})
    return bool(set(statuses) & {"published", "active", "live"}) or any(value is True for value in flags)


def list_products(store_key: str) -> list[dict[str, Any]]:
    _, payload = request_json("GET", "/products/list", store_key=store_key, timeout=120)
    return extract_items(payload, ("products", "data", "items"))


def find_product(store_key: str, name: str) -> dict[str, Any] | None:
    for item in list_products(store_key):
        if str(item.get("name") or "").strip() == name:
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


def wait_for_published(store_key: str, name: str, seconds: int = 90) -> dict[str, Any] | None:
    deadline = time.time() + seconds
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        try:
            last = find_product(store_key, name)
            if last and product_is_published(last):
                return last
        except ApiError:
            pass
        time.sleep(5)
    return last if last and product_is_published(last) else None


def publish_product(store_key: str, product_id: str, name: str, evidence: dict[str, Any]) -> dict[str, Any] | None:
    endpoint = f"/products/{urllib.parse.quote(product_id)}/publish"
    for attempt in range(1, 7):
        existing = wait_for_published(store_key, name, 5)
        if existing:
            evidence["publication_evidence"] = "authenticated_product_list"
            return existing
        try:
            _, challenge_payload = request_json(
                "POST", endpoint, store_key=store_key,
                body=MISSING if attempt % 2 else {}, timeout=180, attempts=1,
            )
        except ApiError as exc:
            evidence["challenge_failures"] = int(evidence.get("challenge_failures") or 0) + 1
            evidence["last_challenge_error"] = {"status": exc.status}
            existing = wait_for_published(store_key, name, 20)
            if existing:
                evidence["publication_evidence"] = "published_after_ambiguous_challenge"
                return existing
            time.sleep(min(25, attempt * 3))
            continue

        challenge = first_string(challenge_payload, ["challenge", "question"])
        token = first_string(challenge_payload, ["challenge_token", "challengeToken", "token"])
        if not challenge or not token:
            existing = wait_for_published(store_key, name, 25)
            if existing:
                evidence["publication_evidence"] = "publication_endpoint_and_product_list"
                return existing
            evidence["last_challenge_shape"] = sanitize(challenge_payload)
            continue

        answer = safe_math_answer(challenge)
        evidence["challenge_solved"] = True
        for answer_attempt in range(1, 4):
            try:
                _, result = request_json(
                    "POST", endpoint, store_key=store_key,
                    body={"challenge_token": token, "challenge_answer": answer},
                    timeout=180, attempts=1,
                )
                existing = wait_for_published(store_key, name, 60)
                if existing:
                    evidence["publication_evidence"] = "challenge_answer_and_product_list"
                    return existing
                status = first_string(result, ["status", "state"])
                if status and status.lower() in {"published", "active", "live"}:
                    evidence["publication_evidence"] = "publication_endpoint_terminal_status"
                    return find_product(store_key, name)
            except ApiError as exc:
                evidence["answer_failures"] = int(evidence.get("answer_failures") or 0) + 1
                evidence["last_answer_error"] = {"status": exc.status}
                existing = wait_for_published(store_key, name, 20)
                if existing:
                    evidence["publication_evidence"] = "published_after_ambiguous_answer"
                    return existing
            time.sleep(min(20, answer_attempt * 4))
    return wait_for_published(store_key, name, 30)


def product_files() -> list[dict[str, Any]]:
    task_intake_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Agent Task Intake",
        "type": "object",
        "required": ["objective", "deliverable", "acceptance_criteria", "evidence", "forbidden_actions"],
        "properties": {
            "objective": {"type": "string", "minLength": 1},
            "deliverable": {"type": "string", "minLength": 1},
            "acceptance_criteria": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "deadline": {"type": ["string", "null"]},
            "budget": {"type": "number", "minimum": 0},
            "forbidden_actions": {"type": "array", "items": {"type": "string"}},
        },
    }
    api_matrix = [
        ["case_id", "method", "path", "body", "expected_status", "assertion"],
        ["health", "GET", "/health", "", "200", "JSON body and latency recorded"],
        ["invalid-json", "POST", "/resource", "{", "400", "structured error; no stack trace"],
        ["missing-auth", "GET", "/private", "", "401", "no sensitive details"],
        ["idempotency", "POST", "/orders", "same body twice", "2xx", "same id or safe conflict"],
        ["rate-limit", "GET", "/resource", "burst", "429", "Retry-After present"],
    ]
    matrix_buffer = io.StringIO()
    csv.writer(matrix_buffer).writerows(api_matrix)

    return [
        {
            "name": "One-Cent Agent Task Intake Card",
            "price": 0.01,
            "description": "A tiny machine-readable intake template that forces an AI agent task to define the deliverable, acceptance criteria, evidence, budget, deadline, and forbidden actions before execution.",
            "tags": ["agent", "task-intake", "acceptance-criteria", "template"],
            "files": {
                "README.md": "# One-Cent Agent Task Intake Card\n\nUse this before delegating a bounded task to an AI agent. Fill the YAML or JSON schema, then reject execution when required fields are missing. AI-authored; no external service required.\n",
                "TASK_INTAKE.yaml": "objective: \"\"\ndeliverable: \"\"\nacceptance_criteria:\n  - \"\"\nevidence:\n  - \"\"\ndeadline: null\nbudget: 0\nforbidden_actions:\n  - spend money\n  - expose credentials\n  - contact unapproved recipients\n",
                "task-intake.schema.json": json.dumps(task_intake_schema, indent=2),
                "REVIEW.md": "# Five-minute review\n\n1. Is the result observable?\n2. Can acceptance be tested?\n3. What receipt proves completion?\n4. What may the agent not do?\n5. What is the stop condition?\n",
            },
        },
        {
            "name": "API Error Reproduction and Curl Matrix Kit",
            "price": 0.05,
            "description": "A reproducible API triage pack with a curl case matrix, evidence template, timeout/idempotency checks, and a compact defect report format for public or sanitized endpoints.",
            "tags": ["api", "curl", "debugging", "qa", "openapi"],
            "files": {
                "README.md": "# API Error Reproduction and Curl Matrix Kit\n\nA dependency-free workflow for turning a vague API failure into a minimal reproducible case. Use only against systems you own or are authorized to test.\n",
                "cases.csv": matrix_buffer.getvalue(),
                "run-cases.sh": "#!/usr/bin/env bash\nset -euo pipefail\nBASE_URL=${BASE_URL:?Set BASE_URL}\nprintf 'Run only against an authorized endpoint.\\n'\ncurl -sS -D headers.txt -o body.json -w '%{http_code} %{time_total}\\n' \"$BASE_URL/health\"\npython3 -m json.tool body.json >/dev/null\n",
                "DEFECT_REPORT.md": "# API defect report\n\n## Endpoint and environment\n## Exact request\n## Expected result\n## Actual result\n## Reproduction frequency\n## Response status, headers and body hash\n## Security/privacy redactions\n## Smallest suspected boundary\n",
                "CHECKLIST.md": "# Checks\n\n- Authorization confirmed\n- Secrets removed\n- Exact request captured\n- Timeout distinguished from server failure\n- Retry/idempotency behavior checked\n- Status, headers, body hash and latency recorded\n- Reproduction command exits nonzero on failure\n",
            },
        },
        {
            "name": "CSV and JSON Cleanup Validation Pack",
            "price": 0.05,
            "description": "A local-only Python validator and cleanup runbook for small CSV/JSON datasets: duplicate detection, required fields, type checks, normalized output, and an auditable change report.",
            "tags": ["csv", "json", "data-cleaning", "validation", "python"],
            "files": {
                "README.md": "# CSV and JSON Cleanup Validation Pack\n\nLocal-only starter pack for validating small structured datasets. It never uploads data. Review the schema and backup the source before applying transformations.\n",
                "validate.py": """#!/usr/bin/env python3\nimport csv, json, sys\nfrom pathlib import Path\n\np = Path(sys.argv[1])\nif p.suffix.lower() == '.json':\n    data = json.loads(p.read_text(encoding='utf-8'))\n    rows = data if isinstance(data, list) else [data]\nelif p.suffix.lower() == '.csv':\n    with p.open(newline='', encoding='utf-8-sig') as f:\n        rows = list(csv.DictReader(f))\nelse:\n    raise SystemExit('Expected .csv or .json')\nseen, duplicates = set(), 0\nfor row in rows:\n    key = json.dumps(row, sort_keys=True, ensure_ascii=False)\n    duplicates += key in seen\n    seen.add(key)\nprint(json.dumps({'rows': len(rows), 'exact_duplicates': duplicates, 'unique_rows': len(seen)}, indent=2))\n""",
                "SCHEMA_TEMPLATE.json": json.dumps({"required_fields": [], "types": {}, "unique_by": [], "allowed_nulls": []}, indent=2),
                "CHANGE_REPORT.md": "# Data cleanup change report\n\n- Source file hash:\n- Output file hash:\n- Rows before/after:\n- Exact duplicates removed:\n- Normalizations applied:\n- Rejected rows and reasons:\n- Manual review sample:\n- Remaining uncertainty:\n",
                "CHECKLIST.md": "# Safe cleanup checklist\n\n- Preserve original bytes\n- Declare required fields and types\n- Separate exact duplicates from probable duplicates\n- Do not silently coerce ambiguous values\n- Record every transformation\n- Validate output independently\n",
            },
        },
        {
            "name": "GitHub PR Review Evidence Pack",
            "price": 0.10,
            "description": "A reviewer-ready pack for small pull requests: scope map, risk checklist, test evidence table, backward-compatibility review, and concise handoff templates.",
            "tags": ["github", "pull-request", "code-review", "testing", "release"],
            "files": {
                "README.md": "# GitHub PR Review Evidence Pack\n\nUse this to review a bounded pull request without confusing a passing CI badge with complete evidence. Pair every conclusion with a file, command, or primary-source link.\n",
                "PR_SCOPE.md": "# PR scope map\n\n## Intended behavior\n## Files changed and why\n## Explicit non-goals\n## External interfaces touched\n## Data migration or state transition\n## Rollback path\n",
                "TEST_EVIDENCE.csv": "requirement,test_or_command,result,evidence_location,remaining_gap\n",
                "REVIEW_CHECKLIST.md": "# Review checklist\n\n- Requirement-to-diff traceability\n- Error and timeout paths\n- Idempotency and duplicate side effects\n- Input validation and output encoding\n- Auth/permission boundary\n- Backward compatibility\n- Tests fail before and pass after\n- Docs and migration notes\n- No secrets or personal data in diff/logs\n",
                "HANDOFF.md": "# Reviewer handoff\n\n## What changed\n## Why this is the smallest safe patch\n## Validation performed\n## Known limitations\n## Reviewer attention requested\n## Rollback\n",
            },
        },
        {
            "name": "Autonomous Agent Incident Response Runbook",
            "price": 0.10,
            "description": "A practical incident runbook for autonomous agents: stop execution, contain credentials, reconstruct side effects, distinguish attempted from completed actions, and resume safely.",
            "tags": ["agent-safety", "incident-response", "credentials", "audit", "runbook"],
            "files": {
                "README.md": "# Autonomous Agent Incident Response Runbook\n\nFor incidents involving tool-using agents. The priority is containment and evidence preservation, not confident narration. Adapt to your organization and legal obligations.\n",
                "RUNBOOK.md": "# Incident sequence\n\n1. Freeze new side effects.\n2. Revoke or rotate exposed credentials.\n3. Preserve logs, request IDs, commit SHAs and transaction identifiers.\n4. Classify each action: proposed, attempted, accepted, completed, settled, unknown.\n5. Reconcile external systems directly.\n6. Notify the accountable owner with confirmed facts and gaps.\n7. Patch the control failure and test the stop path.\n8. Resume from the last verified receipt with least privilege.\n",
                "ACTION_LEDGER.csv": "timestamp,system,operation,target,status,external_receipt,credential_scope,owner,next_action\n",
                "CREDENTIAL_CONTAINMENT.md": "# Credential containment\n\n- Identify every copy and log surface\n- Revoke first when exposure is plausible\n- Rotate provider-side credentials\n- Remove material from current branches and artifacts\n- Treat immutable history as compromised\n- Verify the old credential is rejected\n- Issue a narrower replacement\n",
                "POSTMORTEM.md": "# Postmortem\n\n## Impact\n## Timeline\n## Confirmed side effects\n## Unknown or ambiguous actions\n## Root control failure\n## Detection gap\n## Containment and recovery\n## Preventive tests\n## Owner and deadline\n",
            },
        },
    ]


def build_zip(product: Mapping[str, Any]) -> Path:
    name = str(product["name"])
    files = product["files"]
    if not isinstance(files, Mapping) or len(files) < 3:
        raise RuntimeError(f"Insufficient files for {name}")
    forbidden = re.compile(r"(2daimesame|nexaworks|@gmail\.com|\bbak_|\bsk_|private key\s*[:=]|seed phrase\s*[:=])", re.I)
    output = Path(tempfile.gettempdir()) / f"{slugify(name)}.zip"
    manifest_files: dict[str, str] = {}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, raw_content in sorted(files.items()):
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", str(filename)):
                raise RuntimeError(f"Unsafe filename in {name}: {filename}")
            content = str(raw_content).rstrip() + "\n"
            if forbidden.search(content):
                raise RuntimeError(f"Private-looking content in {name}/{filename}")
            archive.writestr(str(filename), content)
            manifest_files[str(filename)] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest = {
            "product": name,
            "generated_at": now_iso(),
            "files": manifest_files,
            "ai_authorship_disclosed": True,
            "external_services_required": False,
        }
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Corrupt archive member: {bad}")
    return output


def choose_category() -> str:
    try:
        _, payload = request_json("GET", "/categories", attempts=2)
        items = extract_items(payload, ("categories", "data", "items"))
        values: list[str] = []
        for item in items:
            value = item.get("slug") or item.get("name") or item.get("id")
            if isinstance(value, str):
                values.append(value)
        for keyword in ("template", "software", "guide", "developer"):
            match = next((value for value in values if keyword in value.lower()), None)
            if match:
                return match
    except Exception:
        pass
    return "templates"


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
    "schema_version": "agentmart-portfolio-v1",
    "started_at": now_iso(),
    "platform": ORIGIN,
    "status": "starting",
    "expenses_usd": 0,
    "products_purchased": 0,
    "verified_income_usdc": 0.0,
    "credentials_recorded_in_plaintext": False,
    "products": [],
    "writes_performed": [],
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

    store_key = str(credentials.get("store_key") or "")
    store_slug = str(credentials.get("store_slug") or "")
    store_id = str(credentials.get("store_id") or "")
    payout_wallet = str(credentials.get("payout_wallet") or "")
    if not re.fullmatch(r"sk_[A-Za-z0-9._~+/=-]{8,}", store_key):
        raise RuntimeError("Invalid store key")
    if not re.fullmatch(r"[a-z0-9-]{3,100}", store_slug):
        raise RuntimeError("Invalid store slug")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", payout_wallet):
        raise RuntimeError("Invalid payout wallet")

    state["store"] = {
        "slug": store_slug,
        "id_hash": short_hash(store_id),
        "payout_wallet": payout_wallet,
    }
    state["status"] = "publishing_portfolio"
    persist("Start diversified AgentMart portfolio", True)

    category = choose_category()
    definitions = product_files()
    for index, definition in enumerate(definitions, 1):
        name = str(definition["name"])
        entry: dict[str, Any] = {
            "name": name,
            "price_usd": float(definition["price"]),
            "public_url": f"{ORIGIN}/store/{store_slug}/products/{slugify(name)}",
            "status": "starting",
            "created_in_this_run": False,
        }
        state["products"] = [item for item in state["products"] if item.get("name") != name] + [entry]
        persist(f"Prepare AgentMart portfolio item {index}")

        product = find_product(store_key, name)
        if not product:
            package = build_zip(definition)
            upload = upload_file(package, store_key)
            file_url = first_string(upload, ["file_url", "fileUrl", "url", "download_url", "downloadUrl"])
            if not file_url:
                raise RuntimeError(f"Upload returned no file URL for {name}")
            _, created = request_json(
                "POST",
                "/products/create",
                store_key=store_key,
                body={
                    "name": name,
                    "price": float(definition["price"]),
                    "description": str(definition["description"]),
                    "type": "download",
                    "file_url": file_url,
                    "category": category,
                    "tags": list(definition["tags"]),
                },
                timeout=120,
            )
            product_id = first_string(created, ["product_id", "productId", "id"])
            if not product_id:
                raise RuntimeError(f"Product creation returned no ID for {name}")
            entry.update({
                "created_in_this_run": True,
                "status": "draft",
                "id_hash": short_hash(product_id),
                "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                "package_bytes": package.stat().st_size,
            })
            state["writes_performed"].append(f"create:{slugify(name)}")
            persist(f"Create AgentMart portfolio item {index}", True)
        else:
            product_id = first_string(product, ["product_id", "productId", "id"])
            if not product_id:
                raise RuntimeError(f"Existing product has no ID for {name}")
            entry["id_hash"] = short_hash(product_id)
            entry["status"] = "published" if product_is_published(product) else "draft"

        if entry["status"] != "published":
            published = publish_product(store_key, product_id, name, entry)
            if not published:
                entry["status"] = "publication_failed"
                persist(f"Record AgentMart portfolio publication failure {index}", True)
                continue
            entry["status"] = "published"
            state["writes_performed"].append(f"publish:{slugify(name)}")
            persist(f"Publish AgentMart portfolio item {index}", True)

    published_count = sum(1 for item in state["products"] if item.get("status") == "published")
    state["published_product_count"] = published_count
    state["status"] = "portfolio_published_waiting_for_paid_sale"
    persist("Start diversified AgentMart portfolio sales monitor", True)

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
            state["analytics_snapshot"] = sanitize(analytics)
            revenue = first_number(analytics, ["revenue", "totalRevenue", "netRevenue", "salesRevenue", "earnings"])
            if revenue > 0:
                state["verified_income_usdc"] = max(state["verified_income_usdc"], revenue)
                state["income_evidence"] = "Authenticated AgentMart analytics reported positive revenue"
        except ApiError:
            pass
        state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "portfolio_published_waiting_for_paid_sale"
        persist("Refresh diversified AgentMart portfolio monitor")
        if state["verified_income_usdc"] > 0:
            break
        time.sleep(30)

    state["finished_at"] = now_iso()
    state["status"] = "income_verified" if state["verified_income_usdc"] > 0 else "run_window_completed_no_sale"
    persist("Finish diversified AgentMart portfolio run", True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        state["status"] = "failed"
        state["failed_at"] = now_iso()
        if isinstance(exc, ApiError):
            state["error"] = {"message": str(exc), "status": exc.status, "payload": sanitize(exc.payload)}
        else:
            state["error"] = sanitize(f"{type(exc).__name__}: {exc}")
        persist("Record AgentMart portfolio failure", True)
        raise
