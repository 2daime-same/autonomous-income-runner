#!/usr/bin/env python3
"""Guarded one-shot WORQ registration and authenticated inventory discovery.

Registration is permitted only when the official machine-readable contract describes
an agent-registration endpoint whose required fields are all operational metadata,
and neither the schema nor the official skill text requires human terms acceptance,
email verification, KYC, a signature, a deposit, a fee, or a purchase.

The credential-bearing response is written only to a private plaintext state file;
the workflow encrypts it before any commit. This program does not bid, claim, accept,
submit, pay, sign, create a wallet, or withdraw.
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

BASE = "https://api.worq.dev"
OPENAPI_URL = BASE + "/openapi.json"
SKILL_URL = "https://worq.dev/skill.md"
PRIVATE_STATE = Path(os.environ.get("WORQ_PRIVATE_STATE", ".worq-state/state.json"))
PUBLIC_OUTPUT = Path(os.environ.get("WORQ_PUBLIC_OUTPUT", "worq-output/result.json"))
TIMEOUT = 45

BLOCKED_CONTRACT_MARKERS = (
    "terms of service",
    "terms and conditions",
    "privacy policy",
    "by registering",
    "by signing up",
    "i agree",
    "agree to the",
    "accept the terms",
    "kyc",
    "identity verification",
    "government id",
    "email verification",
    "verify your email",
    "wallet signature",
    "sign this message",
    "registration fee",
    "application fee",
    "deposit required",
    "purchase credits",
    "buy credits",
    "stake required",
    "bond required",
)
BLOCKED_SCHEMA_FIELDS = (
    "acceptterms",
    "accept_terms",
    "termsaccepted",
    "terms_accepted",
    "agree",
    "agreement",
    "consent",
    "signature",
    "signedmessage",
    "signed_message",
    "password",
    "otp",
    "verificationcode",
    "verification_code",
    "kyc",
    "governmentid",
    "government_id",
    "deposit",
    "payment",
    "creditcard",
    "credit_card",
)
SAFE_FIELD_NAMES = {
    "name",
    "agentname",
    "agent_name",
    "handle",
    "agenthandle",
    "agent_handle",
    "slug",
    "description",
    "bio",
    "capabilities",
    "skills",
    "specialties",
    "tasktypes",
    "task_types",
    "model",
    "modelname",
    "model_name",
    "modelprovider",
    "model_provider",
    "infrastructure",
    "walletaddress",
    "wallet_address",
    "payoutaddress",
    "payout_address",
    "address",
    "hourlyrate",
    "hourly_rate",
    "hourlyrateusdc",
    "hourly_rate_usdc",
}
SECRET_KEYS = {
    "apikey",
    "api_key",
    "rawkey",
    "raw_key",
    "token",
    "accesstoken",
    "access_token",
    "refreshtoken",
    "refresh_token",
    "secret",
    "authorization",
    "privatekey",
    "private_key",
}
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
CREDENTIAL_VALUE_RE = re.compile(r"^(?:worq|wq|api|key|token|sk)_[A-Za-z0-9_-]{12,}$", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def request(method: str, url: str, *, body: Any = None, headers: Mapping[str, str] | None = None) -> tuple[int, Any, Mapping[str, str]]:
    data = None
    merged = {
        "Accept": "application/json,text/markdown,text/plain;q=0.8,*/*;q=0.2",
        "User-Agent": "nexaworks-worq-guarded-agent/1.0",
    }
    if headers:
        merged.update(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        merged["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw
            return response.status, payload, dict(response.headers.items())
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw[:8000]
        return error.code, payload, dict(error.headers.items()) if error.headers else {}


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            compact = normalized.replace("_", "")
            result[key] = "[REDACTED]" if normalized in SECRET_KEYS or compact in SECRET_KEYS else sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        if CREDENTIAL_VALUE_RE.fullmatch(value):
            return "[REDACTED]"
        value = re.sub(r"\b(?:worq|wq|api|key|token|sk)_[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value, flags=re.I)
        return value[:12000]
    return value


def resolve_schema(spec: Mapping[str, Any], schema: Any) -> Mapping[str, Any]:
    if not isinstance(schema, Mapping):
        return {}
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/"):
        current: Any = spec
        for part in reference[2:].split("/"):
            if not isinstance(current, Mapping):
                return {}
            current = current.get(part.replace("~1", "/").replace("~0", "~"))
        return current if isinstance(current, Mapping) else {}
    return schema


def find_registration(spec: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], Mapping[str, Any]] | None:
    paths = spec.get("paths")
    if not isinstance(paths, Mapping):
        return None
    candidates: list[tuple[int, str, Mapping[str, Any], Mapping[str, Any]]] = []
    for path, methods in paths.items():
        if not isinstance(path, str) or not isinstance(methods, Mapping):
            continue
        operation = methods.get("post")
        if not isinstance(operation, Mapping):
            continue
        text = " ".join(
            str(operation.get(key) or "")
            for key in ("summary", "description", "operationId")
        ).lower()
        path_lower = path.lower()
        if "register" not in path_lower + " " + text and "signup" not in path_lower + " " + text:
            continue
        if "agent" not in path_lower + " " + text and "worker" not in path_lower + " " + text:
            continue
        request_body = operation.get("requestBody")
        if not isinstance(request_body, Mapping):
            continue
        content = request_body.get("content")
        if not isinstance(content, Mapping):
            continue
        media = content.get("application/json")
        if not isinstance(media, Mapping):
            continue
        schema = resolve_schema(spec, media.get("schema"))
        score = 10
        if "agent" in path_lower:
            score += 5
        if "public" in text or "autonomous" in text:
            score += 3
        candidates.append((score, path, operation, schema))
    if not candidates:
        return None
    _, path, operation, schema = max(candidates, key=lambda item: item[0])
    return path, operation, schema


def normalized_field(name: str) -> str:
    return name.replace("-", "_").replace(" ", "").lower()


def discover_existing_evm_address(root: Path) -> str | None:
    preferred_parts = ("wallet", "commerce", "payment", "address")
    for path in root.rglob("*.json"):
        relative = path.relative_to(root).as_posix().lower()
        if not any(marker in relative for marker in preferred_parts):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        stack: list[tuple[str, Any]] = [("", value)]
        while stack:
            key, item = stack.pop()
            if isinstance(item, Mapping):
                stack.extend((str(k), v) for k, v in item.items())
            elif isinstance(item, list):
                stack.extend((key, v) for v in item)
            elif isinstance(item, str) and ADDRESS_RE.fullmatch(item):
                key_lower = key.lower()
                if any(marker in key_lower for marker in ("address", "wallet", "evm", "base")):
                    return item
    return None


def sample_for_field(name: str, schema: Mapping[str, Any], address: str | None) -> Any:
    normalized = normalized_field(name)
    field_type = schema.get("type")
    if normalized in {"name", "agentname", "agent_name"}:
        return "BoundaryLedger Agent"
    if normalized in {"handle", "agenthandle", "agent_handle", "slug"}:
        return "boundaryledger-agent"
    if normalized in {"description", "bio"}:
        return "Transparent AI agent for source-backed research, technical analysis, tested code, QA, and structured evidence."
    if normalized in {"capabilities", "skills", "specialties", "tasktypes", "task_types"}:
        return ["research", "technical-writing", "code-review", "qa", "python", "typescript"]
    if normalized in {"modelprovider", "model_provider"}:
        return "OpenAI"
    if normalized in {"model", "modelname", "model_name"}:
        return "GPT-5.6 Pro"
    if normalized == "infrastructure":
        return "PROVIDER_API"
    if normalized in {"walletaddress", "wallet_address", "payoutaddress", "payout_address", "address"}:
        if not address:
            raise ValueError(f"required payout address unavailable for {name}")
        return address
    if normalized in {"hourlyrate", "hourly_rate", "hourlyrateusdc", "hourly_rate_usdc"}:
        return 1
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if field_type == "array":
        return []
    if field_type == "boolean":
        return False
    if field_type in {"integer", "number"}:
        return 1
    raise ValueError(f"unsupported required registration field: {name}")


def build_payload(schema: Mapping[str, Any], address: str | None) -> tuple[dict[str, Any], list[str]]:
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, Mapping):
        properties = {}
    required_names = [str(item) for item in required] if isinstance(required, list) else []
    blockers: list[str] = []
    payload: dict[str, Any] = {}
    for name in required_names:
        normalized = normalized_field(name)
        if normalized in BLOCKED_SCHEMA_FIELDS or any(marker in normalized for marker in BLOCKED_SCHEMA_FIELDS):
            blockers.append(f"blocked required field: {name}")
            continue
        if normalized not in SAFE_FIELD_NAMES:
            blockers.append(f"unsupported required field: {name}")
            continue
        field_schema = resolve_schema({}, properties.get(name)) if isinstance(properties.get(name), Mapping) else {}
        try:
            payload[name] = sample_for_field(name, field_schema, address)
        except ValueError as error:
            blockers.append(str(error))
    for name, field_schema_raw in properties.items():
        name = str(name)
        normalized = normalized_field(name)
        if name in payload or normalized not in SAFE_FIELD_NAMES:
            continue
        if normalized in BLOCKED_SCHEMA_FIELDS or any(marker in normalized for marker in BLOCKED_SCHEMA_FIELDS):
            continue
        field_schema = field_schema_raw if isinstance(field_schema_raw, Mapping) else {}
        try:
            payload[name] = sample_for_field(name, field_schema, address)
        except ValueError:
            pass
    return payload, blockers


def find_credentials(value: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    stack: list[tuple[str, Any]] = [("", value)]
    while stack:
        path, item = stack.pop()
        if isinstance(item, Mapping):
            for key, nested in item.items():
                child = f"{path}.{key}" if path else str(key)
                stack.append((child, nested))
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                stack.append((f"{path}[{index}]", nested))
        elif isinstance(item, str):
            final_key = path.rsplit(".", 1)[-1].replace("-", "_").lower()
            compact = final_key.replace("_", "")
            if final_key in SECRET_KEYS or compact in SECRET_KEYS or CREDENTIAL_VALUE_RE.fullmatch(item):
                found.append((path, item))
    return found


def auth_headers(spec: Mapping[str, Any], credential: str) -> list[dict[str, str]]:
    schemes = (((spec.get("components") or {}).get("securitySchemes") or {}) if isinstance(spec.get("components"), Mapping) else {})
    headers: list[dict[str, str]] = []
    if isinstance(schemes, Mapping):
        for scheme in schemes.values():
            if not isinstance(scheme, Mapping):
                continue
            scheme_type = str(scheme.get("type") or "").lower()
            if scheme_type == "apikey" and str(scheme.get("in") or "").lower() == "header":
                name = str(scheme.get("name") or "X-Api-Key")
                headers.append({name: credential})
            elif scheme_type == "http" and str(scheme.get("scheme") or "").lower() == "bearer":
                headers.append({"Authorization": f"Bearer {credential}"})
    headers.extend([
        {"Authorization": f"Bearer {credential}"},
        {"X-Api-Key": credential},
        {"X-API-Key": credential},
    ])
    unique: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for value in headers:
        marker = tuple(sorted(value.items()))
        if marker not in seen:
            seen.add(marker)
            unique.append(value)
    return unique


def inventory_paths(spec: Mapping[str, Any]) -> list[str]:
    paths = spec.get("paths")
    if not isinstance(paths, Mapping):
        return ["/v1/jobs?status=open&limit=100"]
    candidates: list[str] = []
    for path, methods in paths.items():
        if not isinstance(path, str) or "{" in path or not isinstance(methods, Mapping) or "get" not in methods:
            continue
        lower = path.lower()
        if any(marker in lower for marker in ("job", "task", "bount", "gig", "opportun", "listing")):
            if any(marker in lower for marker in ("mine", "wallet", "earning", "payment", "withdraw", "bid")):
                continue
            candidates.append(path)
    return sorted(set(candidates), key=lambda value: ("open" not in value.lower(), len(value)))


def main() -> int:
    started = now_iso()
    status, openapi, _ = request("GET", OPENAPI_URL)
    skill_status, skill, _ = request("GET", SKILL_URL)
    public: dict[str, Any] = {
        "started_at": started,
        "openapi_status": status,
        "skill_status": skill_status,
        "writes_performed": [],
        "writes_not_performed": ["bid", "claim", "accept", "submit", "payment", "signature", "withdrawal"],
    }
    if status != 200 or not isinstance(openapi, Mapping):
        public["decision"] = "blocked"
        public["blockers"] = ["official OpenAPI unavailable"]
        public["openapi_response"] = sanitize(openapi)
        atomic_json(PUBLIC_OUTPUT, public)
        return 1

    skill_text = skill if isinstance(skill, str) else json.dumps(skill, ensure_ascii=False)
    lower_skill = skill_text.lower()
    contract_hits = sorted(marker for marker in BLOCKED_CONTRACT_MARKERS if marker in lower_skill)
    registration = find_registration(openapi)
    if registration is None:
        public["decision"] = "blocked"
        public["blockers"] = ["agent registration endpoint not found"]
        public["contract_hits"] = contract_hits
        atomic_json(PUBLIC_OUTPUT, public)
        return 0

    path, operation, schema = registration
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    address = discover_existing_evm_address(Path("."))
    payload, schema_blockers = build_payload(schema, address)
    blockers = list(schema_blockers)
    if contract_hits:
        blockers.append("official documentation requires human/legal/financial confirmation")
    operation_text = " ".join(str(operation.get(key) or "") for key in ("summary", "description", "operationId")).lower()
    if any(marker in operation_text for marker in BLOCKED_CONTRACT_MARKERS):
        blockers.append("registration operation itself contains blocked terms")

    public.update({
        "registration_path": path,
        "registration_summary": operation.get("summary"),
        "required_fields": required,
        "payload_fields": sorted(payload),
        "payout_address_available": bool(address),
        "contract_hits": contract_hits,
    })
    if blockers:
        public["decision"] = "blocked"
        public["blockers"] = sorted(set(blockers))
        atomic_json(PUBLIC_OUTPUT, public)
        print(json.dumps({"ok": True, "decision": "blocked", "blockers": public["blockers"]}))
        return 0

    register_url = urllib.parse.urljoin(BASE.rstrip("/") + "/", path.lstrip("/"))
    register_status, register_response, register_headers = request("POST", register_url, body=payload)
    private_state = {
        "registered_at": now_iso(),
        "registration_url": register_url,
        "registration_status": register_status,
        "request_payload": payload,
        "response": register_response,
        "response_headers": {
            key: value
            for key, value in register_headers.items()
            if key.lower() not in {"set-cookie", "authorization"}
        },
    }
    atomic_json(PRIVATE_STATE, private_state, mode=0o600)
    public["writes_performed"] = ["agent_registration"]
    public["registration_status"] = register_status
    public["registration_response"] = sanitize(register_response)

    credentials = find_credentials(register_response)
    public["credential_count"] = len(credentials)
    inventory_results: list[dict[str, Any]] = []
    if credentials:
        credential = credentials[0][1]
        for candidate_path in inventory_paths(openapi)[:20]:
            url = urllib.parse.urljoin(BASE.rstrip("/") + "/", candidate_path.lstrip("/"))
            best: dict[str, Any] | None = None
            for headers in auth_headers(openapi, credential):
                response_status, response_body, _ = request("GET", url, headers=headers)
                attempt = {
                    "status": response_status,
                    "url": url,
                    "auth_header_name": next(iter(headers)),
                    "response": sanitize(response_body),
                }
                if best is None or response_status < int(best["status"]):
                    best = attempt
                if response_status == 200:
                    break
            if best:
                inventory_results.append(best)
    public["inventory_results"] = inventory_results
    public["decision"] = "registered" if 200 <= register_status < 300 else "registration_failed"
    atomic_json(PUBLIC_OUTPUT, public)
    print(json.dumps({"ok": True, "decision": public["decision"], "status": register_status, "credential_count": len(credentials)}))
    return 0 if register_status < 500 else 1


if __name__ == "__main__":
    raise SystemExit(main())
