#!/usr/bin/env python3
"""Convert public Taskmarket opportunities into execution-grade candidates.

The public scanner answers "does suitable funded work exist?". This filter asks
the stricter question: "can this connected runner create, sign, and submit the
required artifact now with a plausible expected value?"

It performs no network calls, wallet operations, signatures, uploads, claims,
pitches, bids, proofs, or submissions. No wallet address or secret is written to
public output.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

INPUT = Path(os.environ.get("TASKMARKET_PUBLIC_OUTPUT", "taskmarket-output/public-scan.json"))
OUTPUT = Path(
    os.environ.get("TASKMARKET_EXECUTION_OUTPUT", "taskmarket-output/executable-scan.json")
)
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
IMAGE_CONTEST = re.compile(
    r"\b(still image|image|poster|illustration|artwork|visual|design plate|data-plate)\b",
    re.I,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def route_state() -> dict[str, bool]:
    worker = os.environ.get("TASKMARKET_WORKER_ADDRESS", "").strip()
    return {
        "worker_wallet_configured": bool(ADDRESS.fullmatch(worker)),
        "eip191_signer_available": env_true("TASKMARKET_SIGNING_AVAILABLE"),
        "submission_client_available": env_true("TASKMARKET_SUBMISSION_CLIENT_AVAILABLE"),
    }


def candidate_text(item: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            str(item.get("title") or ""),
            str(item.get("description_excerpt") or ""),
            " ".join(map(str, item.get("tags") or [])),
        ]
    )


def execution_reasons(item: Mapping[str, Any], route: Mapping[str, bool]) -> list[str]:
    reasons: list[str] = []
    if not item.get("zero_spend_candidate"):
        reasons.append("public_scanner_did_not_mark_zero_spend_candidate")

    if not route["worker_wallet_configured"]:
        reasons.append("worker_wallet_not_configured")
    if not route["eip191_signer_available"]:
        reasons.append("eip191_signer_unavailable")
    if not route["submission_client_available"]:
        reasons.append("authenticated_submission_client_unavailable")

    submissions = int(item.get("submission_count") or 0)
    if submissions >= 10:
        reasons.append("high_competition_at_least_10_submissions")

    capabilities = {str(value) for value in (item.get("capability_matches") or [])}
    if "design" in capabilities and IMAGE_CONTEST.search(candidate_text(item)):
        reasons.append("subjective_image_or_design_contest")

    reward = float(item.get("net_reward_usdc") or item.get("reward_usdc") or 0)
    if reward <= 0:
        reasons.append("no_positive_net_reward")

    hours_left = item.get("hours_left")
    if not isinstance(hours_left, (int, float)) or hours_left <= 2:
        reasons.append("insufficient_or_unknown_time_remaining")

    return sorted(set(reasons))


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("Taskmarket public scan must be a JSON object")

    route = route_state()
    raw_candidates = payload.get("ranked_candidates") or []
    if not isinstance(raw_candidates, list):
        raise RuntimeError("Taskmarket public scan has no ranked_candidates array")

    inspected: list[dict[str, Any]] = []
    executable: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        reasons = execution_reasons(item, route)
        compact = {
            "task_id": item.get("task_id"),
            "task_url": item.get("task_url"),
            "title": item.get("title"),
            "reward_usdc": item.get("reward_usdc"),
            "net_reward_usdc": item.get("net_reward_usdc"),
            "hours_left": item.get("hours_left"),
            "submission_count": item.get("submission_count"),
            "capability_matches": item.get("capability_matches") or [],
            "soft_risks": item.get("soft_risks") or [],
            "execution_exclusions": reasons,
            "execution_ready": not reasons,
        }
        inspected.append(compact)
        if not reasons:
            executable.append(compact)

    result = {
        "generated_at": now_iso(),
        "source": str(INPUT),
        "policy": (
            "Requires a configured worker wallet, EIP-191 signer, authenticated submission "
            "client, positive net reward, more than two hours remaining, fewer than ten "
            "submissions, and no subjective image/design contest signal."
        ),
        "submission_requirement_note": (
            "Taskmarket bounty submission requires workerAddress plus an EIP-191 signature "
            "for taskmarket:submit:<taskId>."
        ),
        "route_state": route,
        "public_zero_spend_candidate_count": int(payload.get("zero_spend_candidate_count") or 0),
        "execution_ready_count": len(executable),
        "execution_ready": executable,
        "inspected": inspected,
        "writes_performed": [],
        "signatures_performed": 0,
        "uploads_performed": 0,
        "verified_income_usdc": 0,
    }
    atomic_write(OUTPUT, result)
    print(
        json.dumps(
            {
                "ok": True,
                "public_candidates": result["public_zero_spend_candidate_count"],
                "execution_ready": len(executable),
                "route_configured": all(route.values()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
