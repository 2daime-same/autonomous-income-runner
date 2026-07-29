#!/usr/bin/env python3
"""Decrypt registered-agent state locally, inspect authenticated jobs, and apply safely.

The worker may submit a reversible application/proposal for a clearly described,
positive-reward job that matches research, writing, data, QA, documentation, code
review, or small coding capabilities. It never claims or accepts a job, signs a
message, transfers funds, purchases credits, pays a fee/bond/deposit, creates a
wallet, submits unfinished work, or withdraws funds.

Private credentials and raw authenticated responses are written only to the
private output path. Public output is recursively sanitized.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

TIMEOUT = 45


@dataclass(frozen=True)
class Market:
    name: str
    base: str
    openapi: str
    cms_path: str


MARKETS = (
    Market("worq", "https://api.worq.dev", "https://api.worq.dev/openapi.json", "worq-output/private-state.cms"),
    Market("agenthire", "https://api.agenthire.app", "https://api.agenthire.app/openapi.json", "agenthire-output/private-state.cms"),
    Market("agrenting", "https://agrenting.com", "https://agrenting.com/openapi.json", "agrenting-output/private-state.cms"),
    Market("agentjob", "https://agent-job.ai", "https://agent-job.ai/openapi.json", "agentjob-output/private-state.cms"),
    Market("clawlancer", "https://clawlancer.ai", "https://clawlancer.ai/openapi.json", "clawlancer-output/private-state.cms"),
)

SECRET_KEYS = {
    "apikey", "api_key", "rawkey", "raw_key", "token", "accesstoken", "access_token",
    "refreshtoken", "refresh_token", "secret", "authorization", "privatekey", "private_key",
    "password", "cookie", "set_cookie",
}
CREDENTIAL_RE = re.compile(r"^(?:worq|wq|agenthire|ah|agrenting|agentjob|clawlancer|api|key|token|sk)_[A-Za-z0-9_-]{12,}$", re.I)

OUTLAY_MARKERS = (
    "registration fee", "application fee", "processing fee", "listing fee", "pay to apply",
    "pay to claim", "deposit required", "bond required", "stake required", "buy credits",
    "purchase credits", "fund a child bounty", "fully fund", "gas fee required",
)
SOCIAL_MARKERS = (
    "referral", "refer a", "invite a", "post on x", "post on twitter", "tweet", "farcaster",
    "social media post", "promote on", "town square", "linkedin post", "instagram", "tiktok",
)
PHYSICAL_OR_IDENTITY = (
    "physical device", "record a video", "video proof", "phone number", "sms verification",
    "government id", "identity verification", "in-person", "selfie", "face verification",
)
HIGH_RISK = (
    "exploit", "penetration test", "credential stuffing", "bypass authentication", "malware",
    "phishing", "ddos", "denial of service", "steal", "exfiltrate", "weapon", "adult content",
    "porn", "gambling", "casino", "betting", "medical diagnosis", "legal advice", "trade crypto",
    "buy token", "short sell", "investment advice",
)
CAPABILITY_MARKERS = (
    "research", "analysis", "writing", "article", "documentation", "docs", "qa", "quality assurance",
    "test plan", "code review", "review code", "data", "csv", "json", "python", "typescript",
    "javascript", "bug report", "fact check", "fact-check", "technical", "report", "summar",
    "competitor", "market research", "product research", "small fix", "unit test",
)
APPLICATION_WORDS = ("apply", "application", "bid", "proposal")
PROHIBITED_WRITE_WORDS = ("claim", "accept", "start", "submit", "approve", "pay", "deposit", "withdraw", "purchase", "buy", "sign")
BLOCKED_REQUIRED_FIELDS = (
    "terms", "agree", "agreement", "consent", "signature", "password", "otp", "verification",
    "payment", "deposit", "bond", "stake", "creditcard", "credit_card",
)
SAFE_APPLICATION_FIELDS = {
    "jobid", "job_id", "taskid", "task_id", "callid", "call_id", "opportunityid", "opportunity_id",
    "agentid", "agent_id", "workerid", "worker_id",
    "coverletter", "cover_letter", "covermessage", "cover_message", "message", "proposal", "note",
    "bidamount", "bid_amount", "proposedamount", "proposed_amount", "amount", "rate", "price",
    "proposeddeadline", "proposed_deadline", "deadline", "estimatedcompletion", "estimated_completion",
    "model", "modelname", "model_name", "modelprovider", "model_provider",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat()


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


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, nested in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            compact = normalized.replace("_", "")
            result[key] = "[REDACTED]" if normalized in SECRET_KEYS or compact in SECRET_KEYS else sanitize(nested)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        if CREDENTIAL_RE.fullmatch(value):
            return "[REDACTED]"
        value = re.sub(r"\b(?:worq|wq|agenthire|ah|agrenting|agentjob|clawlancer|api|key|token|sk)_[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value, flags=re.I)
        value = re.sub(r"\b0x[a-fA-F0-9]{64}\b", "[REDACTED_HEX]", value)
        return value[:16000]
    return value


def request(method: str, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None) -> tuple[int, Any, Mapping[str, str]]:
    merged = {"Accept": "application/json", "User-Agent": "nexaworks-registered-market-worker/1.0"}
    if headers:
        merged.update(headers)
    data = None
    if body is not None:
        merged["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, headers=merged, data=data, method=method)
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
            payload = raw[:12000]
        return error.code, payload, dict(error.headers.items()) if error.headers else {}


def find_certificate(repo: Path) -> list[Path]:
    result: list[Path] = []
    for path in list(repo.rglob("*.crt")) + list(repo.rglob("*.pem")):
        try:
            if "BEGIN CERTIFICATE" in path.read_text(encoding="utf-8", errors="ignore"):
                result.append(path)
        except OSError:
            pass
    return result


def find_private_keys(explicit: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    for base in (Path("/mnt/data"), Path.home()):
        if not base.exists():
            continue
        candidates.extend(base.rglob("*.key"))
        candidates.extend(base.rglob("*.pem"))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
            if resolved not in seen and path.is_file():
                seen.add(resolved)
                unique.append(path)
        except OSError:
            continue
    return unique


def decrypt_state(cms: Path, keys: list[Path], certs: list[Path]) -> Mapping[str, Any] | None:
    if not cms.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="registered-market-state-") as temporary:
        output = Path(temporary) / "state.json"
        for key in keys:
            for cert in certs:
                command = [
                    "openssl", "cms", "-decrypt", "-binary", "-inform", "DER",
                    "-in", str(cms), "-inkey", str(key), "-recip", str(cert), "-out", str(output),
                ]
                completed = subprocess.run(command, capture_output=True)
                if completed.returncode != 0:
                    continue
                try:
                    value = json.loads(output.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(value, Mapping):
                    return value
    return None


def find_credentials(value: Any) -> list[str]:
    found: list[str] = []
    stack: list[tuple[str, Any]] = [("", value)]
    while stack:
        path, item = stack.pop()
        if isinstance(item, Mapping):
            for key, nested in item.items():
                stack.append((f"{path}.{key}" if path else str(key), nested))
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                stack.append((f"{path}[{index}]", nested))
        elif isinstance(item, str):
            key = path.rsplit(".", 1)[-1].replace("-", "_").lower()
            compact = key.replace("_", "")
            if key in SECRET_KEYS or compact in SECRET_KEYS or CREDENTIAL_RE.fullmatch(item):
                found.append(item)
    return list(dict.fromkeys(found))


def find_identifier(value: Any) -> str | None:
    preferred = ("agent_id", "agentid", "worker_id", "workerid", "id")
    if isinstance(value, Mapping):
        normalized = {str(key).replace("-", "_").lower(): nested for key, nested in value.items()}
        for key in preferred:
            candidate = normalized.get(key)
            if isinstance(candidate, (str, int)) and str(candidate):
                return str(candidate)
        for nested in value.values():
            result = find_identifier(nested)
            if result:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = find_identifier(nested)
            if result:
                return result
    return None


def auth_headers(spec: Mapping[str, Any], credential: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    components = spec.get("components")
    schemes = components.get("securitySchemes") if isinstance(components, Mapping) else None
    if isinstance(schemes, Mapping):
        for scheme in schemes.values():
            if not isinstance(scheme, Mapping):
                continue
            if str(scheme.get("type") or "").lower() == "apikey" and str(scheme.get("in") or "").lower() == "header":
                result.append({str(scheme.get("name") or "X-Api-Key"): credential})
            elif str(scheme.get("type") or "").lower() == "http" and str(scheme.get("scheme") or "").lower() == "bearer":
                result.append({"Authorization": f"Bearer {credential}"})
    result.extend((
        {"Authorization": f"Bearer {credential}"},
        {"X-Api-Key": credential},
        {"X-API-Key": credential},
    ))
    unique: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for headers in result:
        marker = tuple(sorted(headers.items()))
        if marker not in seen:
            seen.add(marker)
            unique.append(headers)
    return unique


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


def server_bases(market: Market, spec: Mapping[str, Any]) -> list[str]:
    values = [market.base.rstrip("/")]
    servers = spec.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if isinstance(server, Mapping) and isinstance(server.get("url"), str):
                raw = server["url"]
                if raw.startswith("http://") or raw.startswith("https://"):
                    values.append(raw.rstrip("/"))
                else:
                    values.append(urllib.parse.urljoin(market.base.rstrip("/") + "/", raw).rstrip("/"))
    return list(dict.fromkeys(values))


def inventory_operations(spec: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    result: list[tuple[str, Mapping[str, Any]]] = []
    paths = spec.get("paths")
    if not isinstance(paths, Mapping):
        return result
    for path, methods in paths.items():
        if not isinstance(path, str) or "{" in path or not isinstance(methods, Mapping):
            continue
        operation = methods.get("get")
        if not isinstance(operation, Mapping):
            continue
        lower = (path + " " + str(operation.get("summary") or "") + " " + str(operation.get("operationId") or "")).lower()
        if not any(marker in lower for marker in ("job", "task", "bount", "gig", "opportun", "listing", "call")):
            continue
        if any(marker in lower for marker in ("mine", "earning", "wallet", "payment", "withdraw", "application", "bid")):
            continue
        result.append((path, operation))
    return result


def unwrap(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "items", "jobs", "tasks", "bounties", "gigs", "opportunities", "listings", "calls", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
            if isinstance(candidate, Mapping):
                nested = unwrap(candidate)
                if nested:
                    return nested
    return []


def pick(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item.get(key)
    return None


def parse_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value.replace(",", ""))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    if isinstance(value, Mapping):
        for key in ("amountUsd", "amount_usd", "usd", "usdc", "amount", "value", "budget", "reward", "cents"):
            result = parse_number(value.get(key))
            if result is not None:
                return result / 100 if key == "cents" else result
    return None


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def compact_job(market: str, item: Mapping[str, Any]) -> dict[str, Any]:
    reward_raw = pick(item, "reward", "rewardAmount", "reward_amount", "budget", "budgetUsdc", "budget_usdc", "amount", "bounty", "bounty_cents", "compensation", "pay")
    amount = parse_number(reward_raw)
    if item.get("bounty_cents") is not None and isinstance(item.get("bounty_cents"), (int, float)):
        amount = float(item["bounty_cents"]) / 100.0
    return {
        "market": market,
        "id": pick(item, "id", "jobId", "job_id", "taskId", "task_id", "callId", "call_id", "slug"),
        "title": str(pick(item, "title", "name", "jobTitle", "task_title") or "")[:500],
        "description": str(pick(item, "description", "summary", "details", "goal", "prompt", "inputData") or "")[:5000],
        "status": str(pick(item, "status", "state", "availability") or ""),
        "amount": amount,
        "reward_raw": sanitize(reward_raw),
        "currency": pick(item, "currency", "rewardCurrency", "token", "paymentCurrency"),
        "deadline": pick(item, "deadline", "deadlineAt", "deadline_at", "expiresAt", "expires_at"),
        "payment_status": str(pick(item, "paymentStatus", "payment_status", "escrowStatus", "escrow_status") or ""),
        "acceptance": sanitize(pick(item, "acceptanceCriteria", "acceptance_criteria", "criteria", "deliverables", "outputSchema")),
        "url": str(pick(item, "url", "publicUrl", "public_url", "jobUrl", "job_url") or "")[:2000],
        "raw": sanitize(item),
    }


def evaluate(job: Mapping[str, Any]) -> tuple[bool, list[str], float]:
    text = "\n".join(str(job.get(key) or "") for key in ("title", "description", "acceptance", "raw")).lower()
    blockers: list[str] = []
    status = str(job.get("status") or "").lower()
    if status and not any(marker in status for marker in ("open", "active", "available", "posted", "new")):
        blockers.append(f"not open: {status}")
    deadline = parse_time(job.get("deadline"))
    if deadline and deadline <= now():
        blockers.append("deadline passed")
    amount = job.get("amount")
    numeric_amount = float(amount) if isinstance(amount, (int, float)) else 0.0
    if numeric_amount <= 0:
        blockers.append("no positive reward")
    for marker in OUTLAY_MARKERS:
        if marker in text:
            blockers.append(marker)
    for marker in SOCIAL_MARKERS:
        if marker in text:
            blockers.append(marker)
    for marker in PHYSICAL_OR_IDENTITY:
        if marker in text:
            blockers.append(marker)
    for marker in HIGH_RISK:
        if marker in text:
            blockers.append(marker)
    capability_matches = sum(1 for marker in CAPABILITY_MARKERS if marker in text)
    if capability_matches == 0:
        blockers.append("capability mismatch or unclear task")
    if not str(job.get("title") or "").strip():
        blockers.append("missing title")
    if not str(job.get("description") or "").strip() and not job.get("acceptance"):
        blockers.append("missing scope and acceptance criteria")
    score = numeric_amount + capability_matches * 5
    if deadline:
        score += min(10.0, max(0.0, (deadline - now()).total_seconds() / 86400))
    return not blockers, sorted(set(blockers)), score


def application_operations(spec: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    result: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    paths = spec.get("paths")
    if not isinstance(paths, Mapping):
        return result
    for path, methods in paths.items():
        if not isinstance(path, str) or not isinstance(methods, Mapping):
            continue
        operation = methods.get("post")
        if not isinstance(operation, Mapping):
            continue
        text = (path + " " + str(operation.get("summary") or "") + " " + str(operation.get("operationId") or "")).lower()
        if not any(word in text for word in APPLICATION_WORDS):
            continue
        if any(word in text for word in PROHIBITED_WRITE_WORDS):
            continue
        body = operation.get("requestBody")
        schema: Mapping[str, Any] = {}
        if isinstance(body, Mapping) and isinstance(body.get("content"), Mapping):
            media = body["content"].get("application/json")
            if isinstance(media, Mapping):
                schema = resolve_schema(spec, media.get("schema"))
        result.append((path, operation, schema))
    return result


def normalize(name: str) -> str:
    return name.replace("-", "_").replace(" ", "").lower()


def application_payload(schema: Mapping[str, Any], job: Mapping[str, Any], agent_id: str | None) -> tuple[dict[str, Any], list[str]]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    required = [str(item) for item in schema.get("required", [])] if isinstance(schema.get("required"), list) else []
    payload: dict[str, Any] = {}
    blockers: list[str] = []
    amount = float(job.get("amount") or 0)
    bid = max(0.01, round(amount * 0.9, 4))
    job_id = str(job.get("id") or "")
    deadline = parse_time(job.get("deadline")) or (now() + timedelta(days=1))
    proposed = min(deadline, now() + timedelta(hours=24)).replace(microsecond=0).isoformat()
    cover = (
        "Transparent AI agent application. I can complete the stated research, documentation, QA, data, "
        "or small-code scope with source citations, reproducibility evidence, tests where applicable, and "
        "clear disclosure that the work is AI-produced. I will not fabricate human experience or attributes."
    )

    def value_for(field: str, field_schema: Mapping[str, Any]) -> Any:
        name = normalize(field)
        if name in {"jobid", "job_id", "taskid", "task_id", "callid", "call_id", "opportunityid", "opportunity_id"}:
            return job_id
        if name in {"agentid", "agent_id", "workerid", "worker_id"}:
            if not agent_id:
                raise ValueError("agent identifier unavailable")
            return agent_id
        if name in {"coverletter", "cover_letter", "covermessage", "cover_message", "message", "proposal", "note"}:
            return cover
        if name in {"bidamount", "bid_amount", "proposedamount", "proposed_amount", "amount", "rate", "price"}:
            return bid
        if name in {"proposeddeadline", "proposed_deadline", "deadline", "estimatedcompletion", "estimated_completion"}:
            return proposed
        if name in {"modelprovider", "model_provider"}:
            return "OpenAI"
        if name in {"model", "modelname", "model_name"}:
            return "GPT-5.6 Pro"
        enum = field_schema.get("enum")
        if isinstance(enum, list) and enum:
            return enum[0]
        raise ValueError(f"unsupported field {field}")

    for field in required:
        name = normalize(field)
        if any(marker in name for marker in BLOCKED_REQUIRED_FIELDS):
            blockers.append(f"blocked required field: {field}")
            continue
        if name not in SAFE_APPLICATION_FIELDS:
            blockers.append(f"unsupported required field: {field}")
            continue
        raw_schema = properties.get(field)
        field_schema = raw_schema if isinstance(raw_schema, Mapping) else {}
        try:
            payload[field] = value_for(field, field_schema)
        except ValueError as error:
            blockers.append(str(error))
    for field, raw_schema in properties.items():
        field = str(field)
        if field in payload or normalize(field) not in SAFE_APPLICATION_FIELDS:
            continue
        field_schema = raw_schema if isinstance(raw_schema, Mapping) else {}
        try:
            payload[field] = value_for(field, field_schema)
        except ValueError:
            pass
    return payload, sorted(set(blockers))


def expand_path(path: str, job_id: str, agent_id: str | None) -> str | None:
    value = path
    replacements = {
        "id": job_id,
        "jobId": job_id,
        "job_id": job_id,
        "taskId": job_id,
        "task_id": job_id,
        "callId": job_id,
        "call_id": job_id,
        "opportunityId": job_id,
        "opportunity_id": job_id,
    }
    if agent_id:
        replacements.update({"agentId": agent_id, "agent_id": agent_id, "workerId": agent_id, "worker_id": agent_id})
    for key, replacement in replacements.items():
        value = value.replace("{" + key + "}", urllib.parse.quote(replacement, safe=""))
    if "{" in value or "}" in value:
        return None
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--public-output", type=Path, default=Path("worker-output/registered-markets.json"))
    parser.add_argument("--private-output", type=Path, default=Path("/tmp/registered-markets-private.json"))
    parser.add_argument("--apply", action="store_true", help="Submit at most one reversible application per market")
    args = parser.parse_args()
    repo = args.repo.resolve()
    certs = find_certificate(repo)
    keys = find_private_keys(args.private_key)
    public: dict[str, Any] = {
        "generated_at": now_iso(),
        "safety": "No claim, acceptance, start, submission, signature, payment, fee, bond, deposit, wallet creation, or withdrawal",
        "apply_enabled": args.apply,
        "markets": {},
    }
    private: dict[str, Any] = {"generated_at": now_iso(), "markets": {}}

    for market in MARKETS:
        market_public: dict[str, Any] = {"registered_state_found": False, "applications": []}
        market_private: dict[str, Any] = {}
        state = decrypt_state(repo / market.cms_path, keys, certs)
        if not state:
            market_public["decision"] = "no_decryptable_registered_state"
            public["markets"][market.name] = market_public
            continue
        market_public["registered_state_found"] = True
        credentials = find_credentials(state)
        agent_id = find_identifier(state.get("response") if isinstance(state, Mapping) else state)
        market_public["credential_count"] = len(credentials)
        market_public["agent_id_present"] = bool(agent_id)
        market_private["state"] = state
        if not credentials:
            market_public["decision"] = "credential_not_found"
            public["markets"][market.name] = market_public
            private["markets"][market.name] = market_private
            continue

        spec_status, spec, _ = request("GET", market.openapi)
        if spec_status != 200 or not isinstance(spec, Mapping):
            market_public["decision"] = "openapi_unavailable"
            market_public["openapi_status"] = spec_status
            public["markets"][market.name] = market_public
            private["markets"][market.name] = market_private
            continue

        credential = credentials[0]
        header_options = auth_headers(spec, credential)
        inventory_responses: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        for path, _operation in inventory_operations(spec)[:30]:
            for base in server_bases(market, spec):
                url = urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))
                best: tuple[int, Any, dict[str, str]] | None = None
                for headers in header_options:
                    status, body, _ = request("GET", url, headers=headers)
                    if best is None or status < best[0]:
                        best = (status, body, headers)
                    if status == 200:
                        break
                if best is None:
                    continue
                status, body, used_headers = best
                records = unwrap(body)
                inventory_responses.append({
                    "url": url,
                    "status": status,
                    "auth_header_name": next(iter(used_headers)),
                    "record_count": len(records),
                    "response": sanitize(body),
                })
                if status == 200:
                    jobs.extend(compact_job(market.name, item) for item in records)
                if status == 200 and records:
                    break

        unique_jobs: dict[str, dict[str, Any]] = {}
        for job in jobs:
            marker = str(job.get("id") or "") + "|" + str(job.get("title") or "")
            unique_jobs[marker] = job
        evaluated: list[dict[str, Any]] = []
        for job in unique_jobs.values():
            actionable, blockers, score = evaluate(job)
            evaluated.append({**job, "actionable": actionable, "blockers": blockers, "score": score})
        evaluated.sort(key=lambda value: float(value.get("score") or 0), reverse=True)
        actionable_jobs = [job for job in evaluated if job["actionable"]]
        market_public["decision"] = "authenticated_inventory_read"
        market_public["inventory_endpoints"] = [
            {key: item[key] for key in ("url", "status", "auth_header_name", "record_count")}
            for item in inventory_responses
        ]
        market_public["job_count"] = len(evaluated)
        market_public["actionable_count"] = len(actionable_jobs)
        market_public["evaluated_jobs"] = [sanitize(job) for job in evaluated[:50]]
        market_private["inventory_responses"] = inventory_responses

        if args.apply and actionable_jobs:
            job = actionable_jobs[0]
            job_id = str(job.get("id") or "")
            operations = application_operations(spec)
            submitted = False
            for path, operation, schema in operations:
                expanded = expand_path(path, job_id, agent_id)
                if not expanded:
                    continue
                payload, blockers = application_payload(schema, job, agent_id)
                if blockers:
                    market_public["applications"].append({
                        "job_id": job_id,
                        "path": path,
                        "status": "not_sent",
                        "blockers": blockers,
                    })
                    continue
                for base in server_bases(market, spec):
                    url = urllib.parse.urljoin(base.rstrip("/") + "/", expanded.lstrip("/"))
                    for headers in header_options:
                        status, response_body, _ = request("POST", url, headers=headers, body=payload)
                        private_attempt = {
                            "url": url,
                            "status": status,
                            "request": payload,
                            "response": response_body,
                            "operation": sanitize(operation),
                        }
                        market_private.setdefault("application_attempts", []).append(private_attempt)
                        market_public["applications"].append({
                            "job_id": job_id,
                            "job_title": job.get("title"),
                            "reward_amount": job.get("amount"),
                            "url": url,
                            "status": status,
                            "response": sanitize(response_body),
                        })
                        if 200 <= status < 300:
                            submitted = True
                            break
                    if submitted:
                        break
                if submitted:
                    break
            if submitted:
                market_public["decision"] = "application_submitted"

        public["markets"][market.name] = market_public
        private["markets"][market.name] = market_private

    atomic_json(args.public_output, public)
    atomic_json(args.private_output, private, mode=0o600)
    print(json.dumps({
        "ok": True,
        "applications_submitted": sum(
            1 for value in public["markets"].values() if value.get("decision") == "application_submitted"
        ),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
