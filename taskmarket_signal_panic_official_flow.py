#!/usr/bin/env python3
"""One corrected, zero-spend Signal Panic submission using Taskmarket CLI v1.7.3's public flow.

The flow is reproduced from the pinned official CLI:
1. Sign ``taskmarket:submit:<taskId>`` and request a signed upload URL.
2. PUT the validated ``index.html`` to that URL.
3. Sign ``taskmarket:submit:<taskId>:<artifactKey>`` and POST metadata to
   ``/submissions/from-keys``.

The final endpoint is intentionally *not* retried with an x402 payment signature. If the
server returns HTTP 402, execution fails closed with zero owner-asset outflow.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import taskmarket_wallet as wallet

API = os.environ.get("TASKMARKET_API_URL", "https://api.taskmarket.dev").rstrip("/")
TASK_ID = "0xff2d1349413ba161506a724b74b2755c479c5b70ed57faaf90fc69643becf8d6"
ARTIFACT = Path("deliverables/taskmarket-signal-panic/index.html")
VALIDATION = Path("deliverables/taskmarket-signal-panic/validation-report.json")
AUTHORIZATION = Path("deliverables/taskmarket-signal-panic/official-flow-authorization.json")
STATE_DIR = Path("deliverables/taskmarket-signal-panic/official-flow-state")
ATTEMPT = STATE_DIR / "attempt.json"
EVIDENCE = STATE_DIR / "submission-evidence.json"
ENCRYPTED = STATE_DIR / "private-wallet.cms.b64"
CERTIFICATE = Path("crypto/superteam-state-public.crt")
SECRET = Path(os.environ.get("TASKMARKET_SIGNAL_PANIC_SECRET", "/tmp/taskmarket-signal-panic-official-secret.json"))
TIMEOUT = max(10, min(int(os.environ.get("TASKMARKET_HTTP_TIMEOUT", "60")), 180))
MAX_RESPONSE = 1_000_000
MIME_TYPE = "text/html"
ROLE = "final"

TOKEN_RE = re.compile(r"\b(?:eyJ[A-Za-z0-9._-]{20,}|(?:gh[pousr]|github_pat|sk|pk|api|token|secret)_[A-Za-z0-9._-]{16,})\b", re.I)
SIGNED_URL_RE = re.compile(r"https?://[^\s\"']+", re.I)


class FlowError(RuntimeError):
    def __init__(self, message: str, *, classification: str = "flow_error", status: int | None = None):
        super().__init__(message)
        self.classification = classification
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_text(value: Any, limit: int = 3000) -> str:
    text = str(value or "")[:limit]
    text = TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = SIGNED_URL_RE.sub(lambda match: _sanitize_url(match.group(0)), text)
    return text


def _sanitize_url(raw: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(raw)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "[REDACTED_QUERY]" if parsed.query else "", ""))
    except ValueError:
        return "[REDACTED_URL]"


def sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in {"uploadurl", "signature", "privatekey", "apitoken", "token", "authorization"}:
                result[str(key)] = "[REDACTED]"
            elif normalized == "artifactkey":
                result["artifact_key_sha256"] = sha256_bytes(str(item).encode("utf-8")) if item else None
            else:
                result[str(key)] = sanitize_value(item)
        return result
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, 5000)
    return value


def parse_time(value: Any, label: str) -> datetime:
    if not value:
        raise FlowError(f"{label} is missing", classification="task_invalid")
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FlowError(f"{label} is invalid", classification="task_invalid") from exc
    if result.tzinfo is None:
        raise FlowError(f"{label} lacks timezone", classification="task_invalid")
    return result.astimezone(timezone.utc)


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def amount_usdc(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("amount", "value", "reward"):
            if key in value:
                return amount_usdc(value[key])
        return 0.0
    try:
        result = float(str(value))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if abs(result) >= 10_000:
        result /= 1_000_000
    return round(result, 6)


def http_json(method: str, path_or_url: str, body: Mapping[str, Any] | None = None) -> tuple[int, Any, Mapping[str, str]]:
    url = path_or_url if path_or_url.startswith(("http://", "https://")) else f"{API}{path_or_url}"
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "User-Agent": "boundaryledger-signal-panic-official-flow/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE)
            status = response.status
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE)
        status = exc.code
        response_headers = dict(exc.headers.items()) if exc.headers else {}
    except Exception as exc:  # noqa: BLE001
        raise FlowError(
            f"{method} request failed before an HTTP response: {type(exc).__name__}: {sanitize_text(exc, 500)}",
            classification="network_error",
        ) from exc
    if not raw:
        payload: Any = None
    else:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"unparsed_body": sanitize_text(raw.decode("utf-8", errors="replace"), 2000)}
    return status, payload, response_headers


def put_file(upload_url: str, data: bytes) -> int:
    request = urllib.request.Request(
        upload_url,
        data=data,
        headers={
            "Content-Type": MIME_TYPE,
            "Content-Length": str(len(data)),
            "User-Agent": "boundaryledger-signal-panic-official-flow/1.0",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            response.read(8192)
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(8192)
        raise FlowError(
            f"artifact upload failed ({exc.code}): {sanitize_text(raw.decode('utf-8', errors='replace'), 800)}",
            classification="upload_rejected",
            status=exc.code,
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise FlowError(
            f"artifact upload failed before HTTP response: {type(exc).__name__}: {sanitize_text(exc, 500)}",
            classification="upload_network_error",
        ) from exc
    if not 200 <= status < 300:
        raise FlowError(f"artifact upload returned HTTP {status}", classification="upload_rejected", status=status)
    return status


def unwrap_task(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise FlowError("Taskmarket task response is not an object", classification="task_invalid")
    for key in ("task", "data"):
        nested = payload.get(key)
        if isinstance(nested, Mapping) and (nested.get("id") or nested.get("taskId")):
            return nested
    return payload


def validate_current_task(authorization: Mapping[str, Any]) -> dict[str, Any]:
    status, payload, _ = http_json("GET", f"/api/tasks/{TASK_ID}")
    if status != 200:
        raise FlowError(f"task lookup returned HTTP {status}: {sanitize_text(payload)}", classification="task_lookup_failed", status=status)
    task = unwrap_task(payload)
    task_id = str(task.get("id") or task.get("taskId") or "")
    if task_id.lower() != TASK_ID.lower():
        raise FlowError("Taskmarket returned a different task ID", classification="task_invalid")
    title = str(task.get("title") or task.get("name") or "")
    if "signal panic" not in title.lower():
        raise FlowError(f"unexpected task title: {title!r}", classification="task_invalid")
    if str(task.get("status") or "").lower() != "open":
        raise FlowError(f"task status is {task.get('status')!r}", classification="task_closed")
    if str(task.get("phase") or "").lower() != "active":
        raise FlowError(f"task phase is {task.get('phase')!r}", classification="task_closed")
    if task.get("submissionWindowOpen") is not True:
        raise FlowError("submission window is not open", classification="submission_window_closed")
    expiry = parse_time(task.get("expiryTime") or task.get("expiresAt"), "task expiry")
    if datetime.now(timezone.utc) >= expiry:
        raise FlowError("task has expired", classification="task_expired")
    reward = amount_usdc(task.get("reward"))
    minimum = float(authorization.get("minimum_reward_usdc") or 0)
    if reward < minimum:
        raise FlowError(f"reward dropped below authorized minimum: {reward}", classification="reward_changed")
    if task.get("stakeRequired") is True or integer(task.get("stakeBps")) != 0:
        raise FlowError("task requires a worker stake", classification="owner_asset_outflow_required")
    submissions = integer(task.get("submissionCount"), -1)
    maximum = integer(authorization.get("maximum_reported_submissions"), -1)
    if submissions < 0 or maximum < 0 or submissions > maximum:
        raise FlowError(
            f"reported submission count {submissions} exceeds authorized maximum {maximum}",
            classification="competition_guard_failed",
        )
    worker_submit = []
    for item in task.get("pendingActions") or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("role") or "").lower() == "worker" and str(item.get("action") or "").lower() == "submit":
            worker_submit.append(item)
    if len(worker_submit) != 1:
        raise FlowError("exactly one worker submit action was not present", classification="task_contract_changed")
    if worker_submit[0].get("requiresPayment") is not False:
        raise FlowError("worker submit action requires payment", classification="owner_asset_outflow_required")
    available_until = parse_time(worker_submit[0].get("availableUntil"), "worker submit availability")
    if datetime.now(timezone.utc) >= available_until:
        raise FlowError("worker submit action expired", classification="submission_window_closed")
    return {
        "task_id": task_id,
        "title": title,
        "status": "open",
        "phase": "active",
        "mode": str(task.get("mode") or ""),
        "reward_usdc": reward,
        "net_reward_usdc": amount_usdc(task.get("netReward")),
        "platform_fee_bps": integer(task.get("platformFeeBps")),
        "reported_submission_count": submissions,
        "expiry_time": expiry.replace(microsecond=0).isoformat(),
        "worker_submit_requires_payment": False,
        "stake_required": False,
    }


def load_and_validate_artifact(authorization: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    report = read_json(VALIDATION)
    if not isinstance(report, Mapping) or report.get("browser_smoke") != "passed" or report.get("credential_scan") != "passed":
        raise FlowError("validated Signal Panic browser report is missing or failed", classification="artifact_invalid")
    data = ARTIFACT.read_bytes()
    digest = sha256_bytes(data)
    expected = str(authorization.get("expected_artifact_sha256") or "")
    report_digest = str((report.get("artifact") or {}).get("sha256") or "")
    if not expected or digest != expected or digest != report_digest:
        raise FlowError("artifact hash does not match authorization and validation", classification="artifact_invalid")
    if int((report.get("artifact") or {}).get("runtime_external_assets", -1)) != 0:
        raise FlowError("artifact has runtime external assets", classification="artifact_invalid")
    return data, {
        "path": str(ARTIFACT),
        "file_name": ARTIFACT.name,
        "mime_type": MIME_TYPE,
        "role": ROLE,
        "size_bytes": len(data),
        "sha256": digest,
        "keccak256": "0x" + wallet.keccak256(data).hex(),
        "browser_smoke": "passed",
        "runtime_external_assets": 0,
    }


def sign_message(private_key: int, message: str) -> str:
    signature = wallet.sign_digest(private_key, wallet.personal_sign_digest(message))
    return "0x" + signature.hex()


def encrypt_secret(secret_payload: Mapping[str, Any]) -> str:
    if not CERTIFICATE.is_file():
        raise FlowError(f"encryption certificate not found: {CERTIFICATE}", classification="local_safety_failure")
    with tempfile.TemporaryDirectory(prefix="signal-panic-official-") as directory:
        plain = Path(directory) / "secret.json"
        cipher = Path(directory) / "secret.cms"
        plain.write_text(json.dumps(secret_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(plain, 0o600)
        subprocess.run(
            [
                "openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER",
                "-in", str(plain), "-out", str(cipher), str(CERTIFICATE),
            ],
            check=True,
            capture_output=True,
        )
        encoded = base64.b64encode(cipher.read_bytes()).decode("ascii") + "\n"
    ENCRYPTED.parent.mkdir(parents=True, exist_ok=True)
    temporary = ENCRYPTED.with_suffix(ENCRYPTED.suffix + ".tmp")
    temporary.write_text(encoded, encoding="ascii")
    os.chmod(temporary, 0o600)
    os.replace(temporary, ENCRYPTED)
    return sha256_bytes(ENCRYPTED.read_bytes())


def prepare() -> int:
    wallet.self_test()
    authorization = read_json(AUTHORIZATION)
    if not isinstance(authorization, Mapping):
        raise FlowError("authorization file is invalid", classification="authorization_invalid")
    if authorization.get("authorized") is not True or authorization.get("authorization_consumed") is True:
        raise FlowError("corrected submission is not currently authorized", classification="authorization_invalid")
    if authorization.get("zero_spend_required") is not True or authorization.get("retry_payment_on_402") is not False:
        raise FlowError("zero-spend/payment-fail-closed authorization is missing", classification="authorization_invalid")
    expires = parse_time(authorization.get("expires_at"), "authorization expiry")
    if datetime.now(timezone.utc) >= expires:
        raise FlowError("authorization expired", classification="authorization_invalid")
    if ATTEMPT.exists() or EVIDENCE.exists() or ENCRYPTED.exists():
        raise FlowError("official-flow state already exists; refusing to overwrite", classification="duplicate_attempt_guard")

    data, artifact = load_and_validate_artifact(authorization)
    task = validate_current_task(authorization)
    private_key = secrets.randbelow(wallet.ORDER - 1) + 1
    public_point = wallet.scalar_multiply(private_key)
    address = wallet.checksum_address(public_point)
    base_message = f"taskmarket:submit:{TASK_ID}"
    base_signature = sign_message(private_key, base_message)
    secret_payload = {
        "schema_version": "taskmarket-signal-panic-official-secret-v1",
        "attempt_id": authorization.get("attempt_id"),
        "generated_at": utc_now(),
        "private_key": "0x" + private_key.to_bytes(32, "big").hex(),
        "worker_address": address,
        "base_message": base_message,
        "base_signature": base_signature,
        "purpose": "One corrected zero-spend Signal Panic submission using Taskmarket CLI v1.7.3 public endpoints.",
    }
    write_json(SECRET, secret_payload, 0o600)
    encrypted_sha256 = encrypt_secret(secret_payload)
    attempt = {
        "schema_version": "taskmarket-signal-panic-official-attempt-v1",
        "attempt_id": authorization.get("attempt_id"),
        "status": "in_progress",
        "prepared_at": utc_now(),
        "finished_at": None,
        "worker_address": address,
        "task": task,
        "artifact_evidence": artifact,
        "flow_contract": {
            "cli_package": "@lucid-agents/taskmarket@1.7.3",
            "request_upload_path": f"/api/tasks/{TASK_ID}/submissions/request-upload-url",
            "upload_method": "PUT",
            "final_submit_path": f"/api/tasks/{TASK_ID}/submissions/from-keys",
            "payment_retry_on_http_402": False,
            "device_registration_required_by_api_flow": False,
            "legal_acceptance_required": False,
        },
        "encrypted_wallet": {
            "path": str(ENCRYPTED),
            "sha256": encrypted_sha256,
            "certificate": str(CERTIFICATE),
        },
        "external_writes_performed": [],
        "payment_signature_created": False,
        "public_signature_exposed": False,
        "private_key_published": False,
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
        "verified_receivable_usdc": 0,
    }
    write_json(ATTEMPT, attempt, 0o644)
    print(json.dumps({"ok": True, "status": "prepared", "worker_address": address, "task_id": TASK_ID}))
    return 0


def append_write(attempt: dict[str, Any], method: str, path: str, purpose: str, status: int | None = None) -> None:
    attempt.setdefault("external_writes_performed", []).append({
        "method": method,
        "path": path,
        "purpose": purpose,
        "count": 1,
        "automatic_retry": False,
        "http_status": status,
    })
    write_json(ATTEMPT, attempt, 0o644)


def consume_authorization(result: str) -> None:
    authorization = read_json(AUTHORIZATION)
    if not isinstance(authorization, dict):
        return
    authorization["authorized"] = False
    authorization["authorization_consumed"] = True
    authorization["consumed_at"] = utc_now()
    authorization["consumption_result"] = result
    authorization["retry_authorized"] = False
    write_json(AUTHORIZATION, authorization, 0o644)


def submit() -> int:
    authorization = read_json(AUTHORIZATION)
    attempt = read_json(ATTEMPT)
    secret_payload = read_json(SECRET)
    if not isinstance(authorization, Mapping) or not isinstance(attempt, dict) or not isinstance(secret_payload, Mapping):
        raise FlowError("official-flow state is invalid", classification="local_safety_failure")
    if authorization.get("authorized") is not True or authorization.get("authorization_consumed") is True:
        raise FlowError("corrected submission authorization is unavailable", classification="authorization_invalid")
    if attempt.get("status") != "in_progress" or attempt.get("external_writes_performed"):
        raise FlowError("attempt is not clean and pending", classification="duplicate_attempt_guard")
    if sha256_bytes(ENCRYPTED.read_bytes()) != str((attempt.get("encrypted_wallet") or {}).get("sha256") or ""):
        raise FlowError("encrypted wallet integrity check failed", classification="local_safety_failure")

    data, artifact = load_and_validate_artifact(authorization)
    task = validate_current_task(authorization)
    if task["task_id"].lower() != str((attempt.get("task") or {}).get("task_id") or "").lower():
        raise FlowError("task changed between preparation and submission", classification="task_contract_changed")
    private_key_hex = str(secret_payload.get("private_key") or "")
    private_key = int(private_key_hex.removeprefix("0x"), 16)
    address = str(secret_payload.get("worker_address") or "")
    if wallet.checksum_address(wallet.scalar_multiply(private_key)).lower() != address.lower():
        raise FlowError("private key does not match prepared worker address", classification="local_safety_failure")
    base_signature = str(secret_payload.get("base_signature") or "")

    result_status = "failed"
    classification = "unknown_failure"
    submission_id: str | None = None
    artifact_key_hash: str | None = None
    response_evidence: dict[str, Any] = {}
    error_message: str | None = None
    try:
        upload_path = f"/api/tasks/{TASK_ID}/submissions/request-upload-url"
        request_body = {
            "taskId": TASK_ID,
            "workerAddress": address,
            "signature": base_signature,
            "fileName": ARTIFACT.name,
            "mimeType": MIME_TYPE,
            "role": ROLE,
            "sizeBytes": len(data),
        }
        status, payload, _ = http_json("POST", upload_path, request_body)
        append_write(attempt, "POST", upload_path, "request signed artifact upload URL", status)
        response_evidence["request_upload_http_status"] = status
        response_evidence["request_upload_response"] = sanitize_value(payload)
        if status != 200 or not isinstance(payload, Mapping):
            raise FlowError(
                f"request-upload-url returned HTTP {status}: {sanitize_text(payload)}",
                classification="request_upload_rejected",
                status=status,
            )
        upload_url = str(payload.get("uploadUrl") or "")
        artifact_key = str(payload.get("artifactKey") or "")
        if not upload_url.startswith("https://") or not artifact_key:
            raise FlowError("request-upload-url response lacked required fields", classification="request_upload_invalid")
        artifact_key_hash = sha256_bytes(artifact_key.encode("utf-8"))

        upload_status = put_file(upload_url, data)
        parsed_upload = urllib.parse.urlsplit(upload_url)
        append_write(attempt, "PUT", f"{parsed_upload.scheme}://{parsed_upload.netloc}{parsed_upload.path}", "upload validated index.html", upload_status)
        response_evidence["upload_http_status"] = upload_status
        response_evidence["upload_host"] = parsed_upload.netloc

        bound_message = f"taskmarket:submit:{TASK_ID}:{artifact_key}"
        bound_signature = sign_message(private_key, bound_message)
        final_path = f"/api/tasks/{TASK_ID}/submissions/from-keys"
        final_body = {
            "taskId": TASK_ID,
            "workerAddress": address,
            "artifacts": [
                {
                    "artifactKey": artifact_key,
                    "fileName": ARTIFACT.name,
                    "mimeType": MIME_TYPE,
                    "role": ROLE,
                    "sizeBytes": len(data),
                    "sha256Hash": artifact["sha256"],
                    "keccak256Hash": artifact["keccak256"],
                }
            ],
            "signature": bound_signature,
        }
        status, payload, _ = http_json("POST", final_path, final_body)
        append_write(attempt, "POST", final_path, "create Taskmarket submission from uploaded artifact key", status)
        response_evidence["final_submit_http_status"] = status
        response_evidence["final_submit_response"] = sanitize_value(payload)
        if status == 402:
            raise FlowError(
                "Taskmarket requested x402 payment; zero-spend policy forbids creating or sending a payment authorization",
                classification="payment_required_fail_closed",
                status=402,
            )
        if not 200 <= status < 300 or not isinstance(payload, Mapping):
            raise FlowError(
                f"final submission returned HTTP {status}: {sanitize_text(payload)}",
                classification="final_submit_rejected",
                status=status,
            )
        submission_id = str(payload.get("submissionId") or payload.get("id") or "") or None
        if not submission_id:
            raise FlowError("successful response lacked submissionId", classification="final_submit_invalid")
        result_status = "submitted"
        classification = "submission_created"
    except FlowError as exc:
        classification = exc.classification
        error_message = sanitize_text(exc, 1200)
        result_status = "rejected" if exc.status and 400 <= exc.status < 500 else "failed"
    except Exception as exc:  # noqa: BLE001
        classification = "unexpected_error"
        error_message = f"{type(exc).__name__}: {sanitize_text(exc, 1000)}"
        result_status = "failed"
    finally:
        attempt = read_json(ATTEMPT)
        attempt["status"] = result_status
        attempt["finished_at"] = utc_now()
        attempt["result_classification"] = classification
        attempt["submission_id"] = submission_id
        attempt["artifact_key_sha256"] = artifact_key_hash
        attempt["payment_signature_created"] = False
        attempt["expenses_usdc"] = 0
        attempt["verified_income_usdc"] = 0
        attempt["verified_receivable_usdc"] = 0
        if error_message:
            attempt["error"] = error_message
        write_json(ATTEMPT, attempt, 0o644)
        evidence = {
            "schema_version": "taskmarket-signal-panic-official-evidence-v1",
            "attempt_id": authorization.get("attempt_id"),
            "task_id": TASK_ID,
            "task_url": f"https://taskmarket.dev/tasks/{TASK_ID}",
            "status": result_status,
            "result_classification": classification,
            "submission_id": submission_id,
            "worker_address": address,
            "artifact_evidence": artifact,
            "artifact_key_sha256": artifact_key_hash,
            "response_evidence": response_evidence,
            "external_writes_performed": attempt.get("external_writes_performed") or [],
            "payment_signature_created": False,
            "payment_retry_performed": False,
            "legal_acceptance_performed": False,
            "device_registration_performed": False,
            "private_key_published": False,
            "public_submission_signature_published": False,
            "expenses_usdc": 0,
            "verified_income_usdc": 0,
            "verified_receivable_usdc": 0,
            "finished_at": utc_now(),
            "error": error_message,
        }
        write_json(EVIDENCE, evidence, 0o644)
        consume_authorization(f"{result_status}:{classification}")
        SECRET.unlink(missing_ok=True)

    print(json.dumps({
        "ok": result_status == "submitted",
        "status": result_status,
        "classification": classification,
        "submission_id": submission_id,
        "expenses_usdc": 0,
    }))
    return 0 if result_status == "submitted" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "submit"))
    args = parser.parse_args()
    return prepare() if args.command == "prepare" else submit()


if __name__ == "__main__":
    raise SystemExit(main())
