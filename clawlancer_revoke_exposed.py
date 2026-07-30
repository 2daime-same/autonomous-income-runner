#!/usr/bin/env python3
"""Contain a Clawlancer agent whose API key was copied into public evidence.

The credential is recovered only from the already-public historical commit, used
once to request deactivation through the documented PATCH agent endpoint, and
never printed or persisted. This does not add any new credential exposure.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE_COMMIT = "adf28fb75cf65d122b836ee1163d18df96ed719d"
SOURCE_PATH = "clawlancer-output/earn-result.json"
BASE = "https://clawlancer.ai/api"
OUTPUT = Path("clawlancer-output/revocation-result.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            if normalized in {
                "api_key", "apikey", "authorization", "auth_header",
                "bearer", "secret", "token", "private_key", "heartbeat_config",
                "details", "request_body", "signed_transaction", "rpc_url",
            }:
                output[key] = "[REDACTED]"
            else:
                output[key] = sanitize(item)
        return output
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\b(?:clw|claw|cl|api)_[A-Za-z0-9._~+/=-]{8,}\b", "[REDACTED]", value)
        value = re.sub(r"Authorization:\s*Bearer\s+\S+", "Authorization: Bearer [REDACTED]", value, flags=re.I)
        value = re.sub(r"https://[^\s\"']*alchemy\.com/v2/[A-Za-z0-9_-]+", "[REDACTED_RPC_URL]", value)
        value = re.sub(r"\b0x[0-9a-fA-F]{128,}\b", "[REDACTED_SIGNED_TRANSACTION]", value)
        value = re.sub(r"\b0x[0-9a-fA-F]{64}\b", "[REDACTED_PRIVATE_KEY]", value)
    return value


def atomic_write(value: Any) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(sanitize(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)


def historic_payload() -> dict[str, Any]:
    raw = subprocess.check_output(
        ["git", "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("Historical evidence was not a JSON object")
    return payload


def extract_credentials(payload: Mapping[str, Any]) -> tuple[str, str]:
    registration = payload.get("registration")
    if not isinstance(registration, Mapping):
        raise RuntimeError("Historical registration object missing")
    agent_id = str(registration.get("agent_id") or "")
    response = registration.get("response")
    heartbeat = response.get("heartbeat_config") if isinstance(response, Mapping) else None
    auth_header = heartbeat.get("auth_header") if isinstance(heartbeat, Mapping) else None
    match = re.fullmatch(r"Authorization:\s*Bearer\s+(\S+)", str(auth_header or ""), flags=re.I)
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", agent_id):
        raise RuntimeError("Historical agent ID is invalid")
    if not match:
        raise RuntimeError("Historical authorization header is missing")
    return agent_id, match.group(1)


def request(method: str, path: str, api_key: str, body: Mapping[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "boundaryledger-credential-containment/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw[:2000]
            return response.status, payload
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw[:2000]
        return error.code, payload


def main() -> int:
    result: dict[str, Any] = {
        "started_at": now_iso(),
        "source_commit": SOURCE_COMMIT,
        "credential_reprinted": False,
        "funds_moved": False,
        "writes_attempted": ["documented PATCH /agents/{id}"],
    }
    try:
        payload = historic_payload()
        agent_id, api_key = extract_credentials(payload)
        result["agent_id"] = agent_id
        patch_body = {
            "name": "REVOKED-EXPOSED-CREDENTIAL",
            "bio": "Credential exposed in public build evidence. This agent is deactivated and must not be used.",
            "is_active": False,
            "active": False,
        }
        status, response = request("PATCH", f"/agents/{agent_id}", api_key, patch_body)
        result["patch_http_status"] = status
        result["patch_response"] = sanitize(response)

        get_status, current = request("GET", f"/agents/{agent_id}", api_key)
        result["verification_http_status"] = get_status
        result["verification"] = sanitize(current)
        serialized = json.dumps(current).lower()
        result["deactivation_confirmed"] = (
            '"is_active": false' in serialized
            or '"active": false' in serialized
            or "revoked-exposed-credential" in serialized
        )
        result["completed_at"] = now_iso()
        atomic_write(result)
        return 0 if status < 500 else 1
    except Exception as error:
        result["failed_at"] = now_iso()
        result["error"] = f"{type(error).__name__}: {error}"
        atomic_write(result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
