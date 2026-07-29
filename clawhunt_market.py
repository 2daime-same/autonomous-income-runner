#!/usr/bin/env python3
"""Register one ClawHunt agent and fetch its currently open problem inventory.

The registration credential is written only to ``.clawhunt-state/state.json``.
The workflow encrypts that file before committing any output. No bid, claim,
solution, payment, or withdrawal action is performed by this discovery step.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE_URL = "https://clawhunt.store"
STATE_FILE = Path(os.environ.get("CLAWHUNT_STATE_FILE", ".clawhunt-state/state.json"))
OUTPUT_DIR = Path(os.environ.get("CLAWHUNT_OUTPUT_DIR", "clawhunt-output"))
TIMEOUT = 45
SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "bearer_token",
    "password",
    "secret",
    "token",
}


class ClawHuntError(RuntimeError):
    pass


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


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            result[key] = "[REDACTED]" if normalized in SECRET_KEYS else sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\bcph_[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


def request_json(
    method: str,
    path: str,
    *,
    body: Mapping[str, Any] | None = None,
    bearer: str | None = None,
    retries: int = 2,
) -> Any:
    url = path if path.startswith("https://") else BASE_URL + path
    headers = {
        "Accept": "application/json",
        "User-Agent": "nexaworks-autonomous-income-runner/1.0",
    }
    data: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                detail: Any = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw[:2000]
            if error.code < 500 or attempt >= retries:
                raise ClawHuntError(
                    f"HTTP {error.code} from {url}: "
                    f"{json.dumps(sanitize(detail), ensure_ascii=False)}"
                ) from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt >= retries:
                break
        time.sleep(2**attempt)
    raise ClawHuntError(f"Request failed for {url}: {last_error}")


def unwrap_problems(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, Mapping):
        for key in ("problems", "items", "data", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def compact_problem(problem: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "title",
        "description",
        "category",
        "difficulty",
        "status",
        "state",
        "budget",
        "budget_usd",
        "bounty",
        "bounty_amount",
        "created_at",
        "updated_at",
        "deadline",
        "bid_count",
        "bids_count",
        "delivery_type",
        "acceptance_criteria",
        "tags",
    )
    return {key: sanitize(problem.get(key)) for key in allowed if problem.get(key) is not None}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        registration = request_json(
            "POST",
            "/api/quick-start",
            body={"name": "BoundaryLedger-Agent"},
            retries=0,
        )
        if not isinstance(registration, Mapping):
            raise ClawHuntError("Registration response was not an object")
        api_key = registration.get("api_key") or registration.get("apiKey")
        agent_id = registration.get("agent_id") or registration.get("agentId")
        if not isinstance(api_key, str) or not api_key.startswith("cph_"):
            raise ClawHuntError("Registration response did not contain a cph_ API key")

        state = {
            "api_key": api_key,
            "agent_id": agent_id,
            "registered_at": now_iso(),
            "base_url": BASE_URL,
        }
        atomic_json(STATE_FILE, state, mode=0o600)

        problems_response = request_json("GET", "/api/v1/problems", bearer=api_key)
        me_response = request_json("GET", "/api/v1/me", bearer=api_key)
        problems = unwrap_problems(problems_response)
        report = {
            "ok": True,
            "fetched_at": now_iso(),
            "agent": sanitize(me_response),
            "problem_count": len(problems),
            "problems": [compact_problem(problem) for problem in problems],
            "registration": {
                "agent_id": agent_id,
                "api_key": "[REDACTED]",
            },
            "writes_performed": ["agent_registration"],
            "writes_not_performed": ["bid", "claim", "solution", "payment", "withdrawal"],
        }
        atomic_json(OUTPUT_DIR / "problems.json", report)
        atomic_json(
            OUTPUT_DIR / "run-summary.json",
            {
                "ok": True,
                "operation": "register_and_list",
                "completed_at": now_iso(),
                "problem_count": len(problems),
            },
        )
        print(json.dumps({"ok": True, "problem_count": len(problems)}))
        return 0
    except ClawHuntError as error:
        atomic_json(
            OUTPUT_DIR / "run-summary.json",
            {"ok": False, "failed_at": now_iso(), "error": str(error)},
        )
        print(f"ClawHunt error: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
