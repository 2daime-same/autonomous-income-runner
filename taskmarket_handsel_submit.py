#!/usr/bin/env python3
"""One-shot, fail-closed submission of the public Handsel label audit to Taskmarket.

The script has two phases:
  prepare: validate the exact funded task, create an ephemeral wallet and
           task-specific EIP-191 signature, encrypt all private material, and
           write a public in-progress receipt before any external write.
  submit:  revalidate the task, send exactly one submission POST, reconcile one
           ambiguous response with a public GET, and write credential-free proof.

No request is retried. No X402 endpoint, fee, deposit, token transfer, or wallet
funding is used.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import taskmarket_wallet as wallet

API = os.environ.get("TASKMARKET_API_URL", "https://api.taskmarket.dev").rstrip("/")
AUTHORIZATION = Path(
    os.environ.get(
        "TASKMARKET_HANDSEL_AUTHORIZATION",
        "deliverables/taskmarket-handsel-network-label-audit/submission-authorization.json",
    )
)
STATE_DIRECTORY = Path(
    os.environ.get(
        "TASKMARKET_HANDSEL_STATE_DIR",
        "deliverables/taskmarket-handsel-network-label-audit/submission-state",
    )
)
ATTEMPT_STATE = STATE_DIRECTORY / "attempt.json"
EVIDENCE = STATE_DIRECTORY / "submission-evidence.json"
ENCRYPTED_WALLET = STATE_DIRECTORY / "private-wallet.cms.b64"
CERTIFICATE = Path(
    os.environ.get("TASKMARKET_WALLET_CERTIFICATE", "crypto/superteam-state-public.crt")
)
SECRET_DIRECTORY = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
MAX_RESPONSE_BYTES = 4_000_000
TIMEOUT_SECONDS = 60
ATTEMPT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{5,100}$")
REDACT = re.compile(
    r"(?:0x[0-9a-fA-F]{64}|eyJ[A-Za-z0-9._-]{20,}|"
    r"(?:token|secret|password|authorization)[=: ]+[^\s,;]+)",
    re.I,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat()


def load_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{path} must contain a JSON object")
    return dict(value)


def write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    wallet.write_json_atomic(path, value, mode)


def request_json(method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "boundaryledger-handsel-label-audit/1.0",
    }
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Taskmarket response exceeded the bounded size")
            return response.status, json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read(min(MAX_RESPONSE_BYTES, 100_000))
        try:
            value = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = {"text": raw.decode("utf-8", errors="replace")[:2_000]}
        return error.code, value


def first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def reward_usdc(task: Mapping[str, Any]) -> float:
    raw = first(task, "reward", "rewardAmount", "reward_amount", "price", "amount")
    try:
        number = float(str(raw))
    except (TypeError, ValueError):
        return 0.0
    return number / 1_000_000 if number > 1_000 else number


def task_text(task: Mapping[str, Any]) -> str:
    return "\n".join(
        str(first(task, key) or "")
        for key in (
            "title",
            "name",
            "description",
            "details",
            "brief",
            "requirements",
            "workRequirements",
        )
    )


def unwrap_submissions(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("submissions", "items", "data", "results"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, Mapping)]
    return []


def worker_of(submission: Mapping[str, Any]) -> str:
    return str(
        first(
            submission,
            "workerAddress",
            "worker_address",
            "worker",
            "submitterAddress",
            "submitter_address",
        )
        or ""
    ).lower()


def submission_id_of(submission: Mapping[str, Any]) -> str | None:
    raw = first(submission, "id", "submissionId", "submission_id")
    return str(raw)[:200] if raw else None


def validate_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    attempt_id = str(value.get("attempt_id") or "")
    if not ATTEMPT_ID.fullmatch(attempt_id):
        raise RuntimeError("invalid authorization attempt_id")
    if value.get("authorized") is not True:
        raise RuntimeError("external submission is not authorized")
    if value.get("zero_spend_required") is not True:
        raise RuntimeError("zero-spend requirement is missing")
    task_id = str(value.get("task_id") or "")
    if not wallet.TASK_ID.fullmatch(task_id):
        raise RuntimeError("invalid authorized task_id")
    expires_at = datetime.fromisoformat(str(value.get("expires_at") or "").replace("Z", "+00:00"))
    authorized_at = datetime.fromisoformat(
        str(value.get("authorized_at") or "").replace("Z", "+00:00")
    )
    current = now()
    if authorized_at.tzinfo is None or expires_at.tzinfo is None:
        raise RuntimeError("authorization timestamps must include a timezone")
    if current < authorized_at.astimezone(timezone.utc) - timedelta(minutes=5):
        raise RuntimeError("authorization timestamp is in the future")
    if current > expires_at.astimezone(timezone.utc):
        raise RuntimeError("submission authorization expired")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 20:
        raise RuntimeError("authorization must list 1-20 artifacts")
    return dict(value)


def validate_task(
    task: Mapping[str, Any],
    submissions: list[Mapping[str, Any]],
    auth: Mapping[str, Any],
) -> dict[str, Any]:
    text = task_text(task)
    lower = text.lower()
    expected_terms = auth.get("expected_title_terms")
    if not isinstance(expected_terms, list) or not expected_terms:
        raise RuntimeError("expected_title_terms is missing")
    missing = [str(term) for term in expected_terms if str(term).lower() not in lower]
    if missing:
        raise RuntimeError(f"task text is missing required terms: {missing}")
    status = str(first(task, "status", "taskStatus", "task_status") or "").lower()
    if status != "open":
        raise RuntimeError(f"task is not open: {status or 'unknown'}")
    mode = str(first(task, "mode", "taskMode", "task_mode") or "bounty").lower()
    if mode != "bounty":
        raise RuntimeError(f"task is not a bounty: {mode}")
    submission_window = first(task, "submissionWindowOpen", "submission_window_open")
    if submission_window is False:
        raise RuntimeError("task submission window is closed")
    deadline_raw = first(
        task,
        "deadline",
        "deadlineAt",
        "deadline_at",
        "expiresAt",
        "expires_at",
        "expiry",
    )
    if deadline_raw:
        try:
            deadline = datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("task returned an invalid deadline") from exc
        if deadline.tzinfo is None:
            raise RuntimeError("task deadline lacks a timezone")
        if now() >= deadline.astimezone(timezone.utc):
            raise RuntimeError("task deadline has passed")
    reward = reward_usdc(task)
    minimum = float(auth.get("minimum_reward_usdc") or 0)
    if reward < minimum:
        raise RuntimeError(f"task reward {reward} is below authorized minimum {minimum}")
    maximum_submissions = int(auth.get("maximum_existing_submissions") or 0)
    if maximum_submissions < 0 or len(submissions) > maximum_submissions:
        raise RuntimeError(
            f"existing submission count {len(submissions)} exceeds limit {maximum_submissions}"
        )
    task_id = str(first(task, "id", "taskId", "task_id") or auth["task_id"])
    if task_id.lower() != str(auth["task_id"]).lower():
        raise RuntimeError("Taskmarket returned a different task ID")
    return {
        "task_id": task_id,
        "title": str(first(task, "title", "name") or text.splitlines()[0])[:1_000],
        "status": status,
        "mode": mode,
        "reward_usdc": reward,
        "submission_count_before": len(submissions),
        "requester": str(
            first(task, "requester", "requesterAddress", "requester_address") or ""
        )[:200]
        or None,
        "deadline": deadline_raw,
        "submission_window_open": submission_window is not False,
    }


def artifact_records(
    auth: Mapping[str, Any], include_content: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    api_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    total = 0
    for raw in auth["artifacts"]:
        if not isinstance(raw, Mapping):
            raise RuntimeError("artifact authorization entry must be an object")
        path = Path(str(raw.get("path") or ""))
        if not path.is_file():
            raise RuntimeError(f"artifact is missing: {path}")
        content = path.read_bytes()
        total += len(content)
        if total > 45_000_000:
            raise RuntimeError("artifact payload exceeds conservative direct-submit limit")
        filename = str(raw.get("file_name") or path.name)
        mime_type = str(raw.get("mime_type") or "application/octet-stream")
        role = str(raw.get("role") or "attachment")
        if role not in {"preview", "source", "final", "attachment"}:
            raise RuntimeError(f"invalid artifact role: {role}")
        evidence_rows.append(
            {
                "path": str(path),
                "file_name": filename,
                "mime_type": mime_type,
                "role": role,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "keccak256": "0x" + wallet.keccak256(content).hex(),
            }
        )
        if include_content:
            api_rows.append(
                {
                    "fileName": filename,
                    "mimeType": mime_type,
                    "role": role,
                    "file": base64.b64encode(content).decode("ascii"),
                }
            )
    return api_rows, evidence_rows


def secret_path(attempt_id: str) -> Path:
    return SECRET_DIRECTORY / f"taskmarket-{attempt_id}-secret.json"


def encrypt_payload(payload: Mapping[str, Any], output: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="taskmarket-submit-") as directory:
        plaintext = Path(directory) / "secret.json"
        plaintext.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(plaintext, 0o600)
        cms = Path(directory) / "secret.cms"
        subprocess.run(
            [
                "openssl",
                "cms",
                "-encrypt",
                "-binary",
                "-aes-256-cbc",
                "-outform",
                "DER",
                "-in",
                str(plaintext),
                "-out",
                str(cms),
                str(CERTIFICATE),
            ],
            check=True,
            capture_output=True,
        )
        ciphertext = cms.read_bytes()
    encoded = base64.b64encode(ciphertext).decode("ascii")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        "\n".join(encoded[index : index + 76] for index in range(0, len(encoded), 76))
        + "\n",
        encoding="ascii",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    return hashlib.sha256(ciphertext).hexdigest()


def prepare() -> int:
    wallet.self_test()
    auth = validate_authorization(load_mapping(AUTHORIZATION))
    if ATTEMPT_STATE.exists():
        existing = load_mapping(ATTEMPT_STATE)
        if existing.get("attempt_id") == auth["attempt_id"]:
            raise RuntimeError(
                f"attempt already recorded with status {existing.get('status')}; refusing reuse"
            )

    task_status, task_body = request_json("GET", f"/api/tasks/{auth['task_id']}")
    if task_status != 200 or not isinstance(task_body, Mapping):
        raise RuntimeError(f"task lookup failed with HTTP {task_status}")
    submissions_status, submissions_body = request_json(
        "GET", f"/api/tasks/{auth['task_id']}/submissions"
    )
    if submissions_status != 200:
        raise RuntimeError(f"submission lookup failed with HTTP {submissions_status}")
    submissions = unwrap_submissions(submissions_body)
    task_snapshot = validate_task(task_body, submissions, auth)
    _, artifacts = artifact_records(auth, include_content=False)

    private_key = secrets.randbelow(wallet.ORDER - 1) + 1
    public_key = wallet.scalar_multiply(private_key)
    worker_address = wallet.checksum_address(public_key)
    message = f"taskmarket:submit:{auth['task_id']}"
    signature = wallet.sign_digest(private_key, wallet.personal_sign_digest(message))
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:64], "big")
    recovered = wallet.recover_public_key(
        int.from_bytes(wallet.personal_sign_digest(message), "big"),
        r,
        s,
        signature[64] - 27,
    )
    if recovered != public_key:
        raise RuntimeError("signature recovery did not match generated wallet")

    secret = {
        "schema_version": "taskmarket-handsel-submission-secret-v1",
        "attempt_id": auth["attempt_id"],
        "generated_at": now_iso(),
        "task_id": auth["task_id"],
        "worker_address": worker_address,
        "private_key": "0x" + private_key.to_bytes(32, "big").hex(),
        "message": message,
        "signature": "0x" + signature.hex(),
        "purpose": "Submit the public Handsel environment-label audit only.",
    }
    private_file = secret_path(str(auth["attempt_id"]))
    write_json(private_file, secret, 0o600)
    encrypted_sha = encrypt_payload(secret, ENCRYPTED_WALLET)

    state = {
        "schema_version": "taskmarket-handsel-submission-attempt-v1",
        "attempt_id": auth["attempt_id"],
        "status": "in_progress",
        "prepared_at": now_iso(),
        "task": task_snapshot,
        "worker_address": worker_address,
        "artifact_evidence": artifacts,
        "encrypted_wallet": {
            "path": str(ENCRYPTED_WALLET),
            "sha256": encrypted_sha,
            "certificate": str(CERTIFICATE),
            "certificate_der_sha256": wallet.certificate_der_sha256(CERTIFICATE),
        },
        "public_signature_exposed": False,
        "external_writes_performed": [],
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
    }
    write_json(ATTEMPT_STATE, state)
    print(
        json.dumps(
            {
                "ok": True,
                "phase": "prepared",
                "attempt_id": auth["attempt_id"],
                "worker_address": worker_address,
                "task_id": auth["task_id"],
                "external_write_performed": False,
            }
        )
    )
    return 0


def sanitize_error(value: Any) -> str:
    return REDACT.sub("[REDACTED]", str(value))[:2_000]


def reconcile(task_id: str, worker_address: str) -> tuple[bool, str | None, int]:
    status, body = request_json("GET", f"/api/tasks/{task_id}/submissions")
    if status != 200:
        return False, None, status
    for submission in unwrap_submissions(body):
        if worker_of(submission) == worker_address.lower():
            return True, submission_id_of(submission), status
    return False, None, status


def submit() -> int:
    auth = validate_authorization(load_mapping(AUTHORIZATION))
    state = load_mapping(ATTEMPT_STATE)
    if state.get("attempt_id") != auth["attempt_id"] or state.get("status") != "in_progress":
        raise RuntimeError("submission state is not the authorized in-progress attempt")

    secret_file = secret_path(str(auth["attempt_id"]))
    worker_address = str(state.get("worker_address") or "")
    post_status: int | None = None
    submission_id: str | None = None
    error: str | None = None
    reconciled = False
    visible = False
    visibility_status: int | None = None
    outcome = "pre_submit_failure"
    post_attempted = False
    artifact_evidence: list[dict[str, Any]] = list(state.get("artifact_evidence") or [])

    try:
        secret = load_mapping(secret_file)
        if secret.get("worker_address") != worker_address:
            raise RuntimeError("ephemeral wallet does not match committed pending state")

        task_status, task_body = request_json("GET", f"/api/tasks/{auth['task_id']}")
        submissions_status, submissions_body = request_json(
            "GET", f"/api/tasks/{auth['task_id']}/submissions"
        )
        if task_status != 200 or not isinstance(task_body, Mapping) or submissions_status != 200:
            raise RuntimeError("task could not be revalidated immediately before submission")
        validate_task(task_body, unwrap_submissions(submissions_body), auth)
        api_artifacts, artifact_evidence = artifact_records(auth, include_content=True)

        body = {
            "taskId": auth["task_id"],
            "workerAddress": worker_address,
            "artifacts": api_artifacts,
            "signature": secret["signature"],
        }
        post_attempted = True
        post_status, response = request_json(
            "POST", f"/api/tasks/{auth['task_id']}/submissions", body
        )
        if (
            post_status in {200, 201}
            and isinstance(response, Mapping)
            and response.get("success") is True
        ):
            outcome = "success"
            raw_id = first(response, "submissionId", "submission_id", "id")
            submission_id = str(raw_id)[:200] if raw_id else None
        else:
            error = f"HTTP {post_status}: {sanitize_error(response)}"
            found, found_id, visibility_status = reconcile(
                str(auth["task_id"]), worker_address
            )
            reconciled = True
            visible = found
            if found:
                outcome = "success"
                submission_id = found_id
            else:
                outcome = "rejected"
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
        error = f"ambiguous transport result: {type(exc).__name__}: {sanitize_error(exc)}"
        if post_attempted:
            found, found_id, visibility_status = reconcile(str(auth["task_id"]), worker_address)
            reconciled = True
            visible = found
            if found:
                outcome = "success"
                submission_id = found_id
            else:
                outcome = "ambiguous"
        else:
            outcome = "pre_submit_failure"
    except Exception as exc:
        error = f"{type(exc).__name__}: {sanitize_error(exc)}"
        if post_attempted:
            found, found_id, visibility_status = reconcile(str(auth["task_id"]), worker_address)
            reconciled = True
            visible = found
            if found:
                outcome = "success"
                submission_id = found_id
            else:
                outcome = "ambiguous"
        else:
            outcome = "pre_submit_failure"

    if post_attempted and not reconciled:
        try:
            visible, visible_id, visibility_status = reconcile(
                str(auth["task_id"]), worker_address
            )
            if outcome == "success" and submission_id is None and visible:
                submission_id = visible_id
        except Exception as exc:
            if error is None:
                error = f"visibility check failed: {type(exc).__name__}: {sanitize_error(exc)}"

    external_writes = (
        [
            {
                "method": "POST",
                "path": f"/api/tasks/{auth['task_id']}/submissions",
                "count": 1,
                "automatic_retry": False,
            }
        ]
        if post_attempted
        else []
    )
    finished = now_iso()
    state.update(
        {
            "status": outcome,
            "finished_at": finished,
            "submission_id": submission_id,
            "post_http_status": post_status,
            "submission_visible_after_write": visible,
            "submission_visibility_http_status": visibility_status,
            "ambiguous_result_reconciled": reconciled,
            "external_writes_performed": external_writes,
            "error": error,
            "expenses_usdc": 0,
            "verified_income_usdc": 0,
        }
    )
    write_json(ATTEMPT_STATE, state)

    evidence = {
        "schema_version": "taskmarket-handsel-submission-evidence-v1",
        "attempt_id": auth["attempt_id"],
        "task_id": auth["task_id"],
        "task_url": f"https://taskmarket.dev/tasks/{auth['task_id']}",
        "status": outcome,
        "submitted_at": finished if outcome == "success" else None,
        "submission_id": submission_id,
        "worker_address": worker_address,
        "artifact_evidence": artifact_evidence,
        "post_http_status": post_status,
        "submission_visible_after_write": visible,
        "submission_visibility_http_status": visibility_status,
        "ambiguous_result_reconciled": reconciled,
        "external_writes_performed": external_writes,
        "signature_scheme": "EIP-191 personal_sign",
        "signature_published": False,
        "private_key_published": False,
        "encrypted_wallet_sha256": state["encrypted_wallet"]["sha256"],
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
        "verified_receivable_usdc": 0,
        "error": error,
    }
    write_json(EVIDENCE, evidence)
    try:
        secret_file.unlink()
    except FileNotFoundError:
        pass

    print(
        json.dumps(
            {
                "ok": outcome == "success",
                "phase": "submitted",
                "status": outcome,
                "submission_id": submission_id,
                "worker_address": worker_address,
                "post_http_status": post_status,
                "external_write_count": len(external_writes),
                "signature_printed": False,
                "private_key_printed": False,
            }
        )
    )
    return 0 if outcome == "success" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "submit"))
    arguments = parser.parse_args()
    return prepare() if arguments.phase == "prepare" else submit()


if __name__ == "__main__":
    raise SystemExit(main())
