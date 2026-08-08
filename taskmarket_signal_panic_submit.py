#!/usr/bin/env python3
"""Fail-closed one-shot Taskmarket submission for the Signal Panic artifact.

This delegates the signing, encrypted-key persistence, one-write POST, and reconciliation
logic to the previously audited direct-submission implementation, while adding current
Taskmarket fields that are material for this specific bounty: expiryTime, phase, reported
submission count, zero worker payment, zero stake, and the exact validated artifact hash.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

os.environ.setdefault(
    "TASKMARKET_HANDSEL_AUTHORIZATION",
    "deliverables/taskmarket-signal-panic/submission-authorization.json",
)
os.environ.setdefault(
    "TASKMARKET_HANDSEL_STATE_DIR",
    "deliverables/taskmarket-signal-panic/submission-state",
)
os.environ.setdefault("TASKMARKET_WALLET_CERTIFICATE", "crypto/superteam-state-public.crt")

import taskmarket_handsel_submit as core  # noqa: E402

ORIGINAL_VALIDATE_TASK = core.validate_task
VALIDATION_REPORT = Path("deliverables/taskmarket-signal-panic/validation-report.json")
ARTIFACT = Path("deliverables/taskmarket-signal-panic/index.html")
EXPECTED_TASK_ID = "0xff2d1349413ba161506a724b74b2755c479c5b70ed57faaf90fc69643becf8d6"


def parse_timestamp(value: Any, label: str) -> datetime:
    if not value:
        raise RuntimeError(f"{label} is missing")
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{label} is invalid") from exc
    if result.tzinfo is None:
        raise RuntimeError(f"{label} lacks a timezone")
    return result.astimezone(timezone.utc)


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def verify_artifact(auth: Mapping[str, Any]) -> dict[str, Any]:
    report = json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    if not isinstance(report, Mapping):
        raise RuntimeError("Signal Panic validation report is invalid")
    if report.get("browser_smoke") != "passed":
        raise RuntimeError("Signal Panic browser validation has not passed")
    if report.get("credential_scan") != "passed":
        raise RuntimeError("Signal Panic credential scan has not passed")
    artifact_report = report.get("artifact")
    if not isinstance(artifact_report, Mapping):
        raise RuntimeError("Signal Panic artifact report is missing")
    content = ARTIFACT.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != str(artifact_report.get("sha256") or ""):
        raise RuntimeError("Signal Panic artifact hash does not match validation report")
    if integer(artifact_report.get("runtime_external_assets"), -1) != 0:
        raise RuntimeError("Signal Panic artifact still has runtime external assets")
    expected = str(auth.get("expected_artifact_sha256") or "")
    if not expected or digest != expected:
        raise RuntimeError("submission authorization is not bound to the validated artifact hash")
    return {
        "artifact_sha256": digest,
        "artifact_size_bytes": len(content),
        "browser_smoke": "passed",
    }


def validate_task(
    task: Mapping[str, Any],
    submissions: list[Mapping[str, Any]],
    auth: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = ORIGINAL_VALIDATE_TASK(task, submissions, auth)
    task_id = str(task.get("id") or task.get("taskId") or auth.get("task_id") or "")
    if task_id.lower() != EXPECTED_TASK_ID.lower():
        raise RuntimeError("Taskmarket returned an unexpected Signal Panic task ID")
    if str(task.get("phase") or "").lower() != "active":
        raise RuntimeError(f"Signal Panic phase is not active: {task.get('phase')!r}")
    expiry = parse_timestamp(task.get("expiryTime"), "Signal Panic expiryTime")
    if datetime.now(timezone.utc) >= expiry:
        raise RuntimeError("Signal Panic task has expired")
    if task.get("submissionWindowOpen") is not True:
        raise RuntimeError("Signal Panic submission window is not explicitly open")
    if task.get("stakeRequired") is True or integer(task.get("stakeBps")) != 0:
        raise RuntimeError("Signal Panic unexpectedly requires a worker stake")

    reported_submissions = integer(task.get("submissionCount"), -1)
    maximum = integer(auth.get("maximum_reported_submissions"), -1)
    if reported_submissions < 0 or maximum < 0:
        raise RuntimeError("reported submission-count guard is missing")
    if reported_submissions > maximum:
        raise RuntimeError(
            f"reported submission count {reported_submissions} exceeds authorized limit {maximum}"
        )

    worker_submit_actions = []
    for raw in task.get("pendingActions") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("role") or "").lower() != "worker":
            continue
        if str(raw.get("action") or "").lower() != "submit":
            continue
        worker_submit_actions.append(dict(raw))
    if len(worker_submit_actions) != 1:
        raise RuntimeError("Taskmarket did not expose exactly one worker submit action")
    action = worker_submit_actions[0]
    if action.get("requiresPayment") is not False:
        raise RuntimeError("Signal Panic worker submission unexpectedly requires payment")
    available_until = parse_timestamp(action.get("availableUntil"), "worker submit availableUntil")
    if datetime.now(timezone.utc) >= available_until:
        raise RuntimeError("Signal Panic worker submit action is no longer available")

    artifact = verify_artifact(auth)
    snapshot.update(
        {
            "phase": "active",
            "expiry_time": expiry.replace(microsecond=0).isoformat(),
            "reported_submission_count": reported_submissions,
            "worker_submit_requires_payment": False,
            "stake_required": False,
            **artifact,
        }
    )
    return snapshot


core.validate_task = validate_task

if __name__ == "__main__":
    raise SystemExit(core.main())
