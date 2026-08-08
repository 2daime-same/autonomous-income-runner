#!/usr/bin/env python3
"""Bubble Brawl configuration for the audited Taskmarket v1.7.3 upload-key flow."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import taskmarket_signal_panic_official_flow as core

TASK_ID = "0xc0654d7b1a1dc86ad4d9bb00187b1e32f929094f614c3fe4ca0305c0bffcedf9"
ROOT = Path("deliverables/taskmarket-bubble-brawl")

core.TASK_ID = TASK_ID
core.ARTIFACT = ROOT / "index.html"
core.VALIDATION = ROOT / "validation-report.json"
core.AUTHORIZATION = ROOT / "official-flow-authorization.json"
core.STATE_DIR = ROOT / "official-flow-state"
core.ATTEMPT = core.STATE_DIR / "attempt.json"
core.EVIDENCE = core.STATE_DIR / "submission-evidence.json"
core.ENCRYPTED = core.STATE_DIR / "private-wallet.cms.b64"
core.SECRET = Path(os.environ.get("TASKMARKET_BUBBLE_BRAWL_SECRET", "/tmp/taskmarket-bubble-brawl-official-secret.json"))


def validate_current_task(authorization: Mapping[str, Any]) -> dict[str, Any]:
    status, payload, _ = core.http_json("GET", f"/api/tasks/{TASK_ID}")
    if status != 200:
        raise core.FlowError(
            f"task lookup returned HTTP {status}: {core.sanitize_text(payload)}",
            classification="task_lookup_failed",
            status=status,
        )
    task = core.unwrap_task(payload)
    task_id = str(task.get("id") or task.get("taskId") or "")
    if task_id.lower() != TASK_ID.lower():
        raise core.FlowError("Taskmarket returned a different task ID", classification="task_invalid")

    title = str(task.get("title") or task.get("name") or "")
    description = str(task.get("description") or "")
    haystack = f"{title} {description}".lower()
    expected_terms = [str(term).strip().lower() for term in authorization.get("expected_title_terms") or [] if str(term).strip()]
    if not expected_terms or not all(term in haystack for term in expected_terms):
        raise core.FlowError("Taskmarket response no longer identifies the Bubble Brawl brief", classification="task_invalid")
    if not title:
        title = "Bubble Brawl"
    if str(task.get("status") or "").lower() != "open":
        raise core.FlowError(f"task status is {task.get('status')!r}", classification="task_closed")
    if str(task.get("phase") or "").lower() != "active":
        raise core.FlowError(f"task phase is {task.get('phase')!r}", classification="task_closed")
    if task.get("submissionWindowOpen") is not True:
        raise core.FlowError("submission window is not open", classification="submission_window_closed")
    expiry = core.parse_time(task.get("expiryTime") or task.get("expiresAt"), "task expiry")
    if datetime.now(timezone.utc) >= expiry:
        raise core.FlowError("task has expired", classification="task_expired")
    reward = core.amount_usdc(task.get("reward"))
    minimum = float(authorization.get("minimum_reward_usdc") or 0)
    if reward < minimum:
        raise core.FlowError(f"reward dropped below authorized minimum: {reward}", classification="reward_changed")
    if task.get("stakeRequired") is True or core.integer(task.get("stakeBps")) != 0:
        raise core.FlowError("task requires a worker stake", classification="owner_asset_outflow_required")
    submissions = core.integer(task.get("submissionCount"), -1)
    maximum = core.integer(authorization.get("maximum_reported_submissions"), -1)
    if submissions < 0 or maximum < 0 or submissions > maximum:
        raise core.FlowError(
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
        raise core.FlowError("exactly one worker submit action was not present", classification="task_contract_changed")
    if worker_submit[0].get("requiresPayment") is not False:
        raise core.FlowError("worker submit action requires payment", classification="owner_asset_outflow_required")
    available_until = core.parse_time(worker_submit[0].get("availableUntil"), "worker submit availability")
    if datetime.now(timezone.utc) >= available_until:
        raise core.FlowError("worker submit action expired", classification="submission_window_closed")
    return {
        "task_id": task_id,
        "title": title,
        "status": "open",
        "phase": "active",
        "mode": str(task.get("mode") or ""),
        "reward_usdc": reward,
        "net_reward_usdc": core.amount_usdc(task.get("netReward")),
        "platform_fee_bps": core.integer(task.get("platformFeeBps")),
        "reported_submission_count": submissions,
        "expiry_time": expiry.replace(microsecond=0).isoformat(),
        "worker_submit_requires_payment": False,
        "stake_required": False,
    }


core.validate_current_task = validate_current_task


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "submit"))
    args = parser.parse_args()
    return core.prepare() if args.command == "prepare" else core.submit()


if __name__ == "__main__":
    raise SystemExit(main())
