#!/usr/bin/env python3
"""Fetch Taskmarket's current public legal-bundle metadata without a wallet or write."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

API = os.environ.get("TASKMARKET_API_URL", "https://api.taskmarket.dev").rstrip("/")
OUTPUT = Path(os.environ.get("TASKMARKET_LEGAL_OUTPUT", "taskmarket-output/legal-bundle-public.json"))
TIMEOUT = max(5, min(int(os.environ.get("TASKMARKET_HTTP_TIMEOUT", "45")), 120))
ACCEPTANCE_STATEMENT = (
    "I agree to the Terms of Service and Acceptable Use Policy, acknowledge the Risk Disclosure, "
    "and confirm that I have been given the Privacy Policy."
)

SENSITIVE_KEYS = {
    "apitoken", "api_token", "deviceencryptionkey", "device_encryption_key", "privatekey",
    "private_key", "signature", "receipt", "authorization", "token",
}


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "").replace("_", "").lower()
            if normalized in {entry.replace("_", "") for entry in SENSITIVE_KEYS}:
                result[str(key)] = None if item is None else "[REDACTED]"
            else:
                result[str(key)] = sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def main() -> int:
    request = urllib.request.Request(
        f"{API}/api/legal/status",
        headers={"Accept": "application/json", "User-Agent": "boundaryledger-taskmarket-legal-probe/1.0"},
        method="GET",
    )
    status = 0
    body = b""
    error: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status = response.status
            body = response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read(2_000_000)
        error = f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - only the sanitized class/message is published
        error = f"{type(exc).__name__}: {str(exc)[:500]}"

    payload: Any = None
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"unparsed_body": body.decode("utf-8", errors="replace")[:2000]}

    report = {
        "schema_version": "taskmarket-public-legal-bundle-probe-v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": f"{API}/api/legal/status",
        "http_status": status,
        "error": error,
        "response": sanitize(payload),
        "cli_package": "@lucid-agents/taskmarket@1.7.3",
        "cli_acceptance_statement": ACCEPTANCE_STATEMENT,
        "wallet_created": False,
        "device_registration_performed": False,
        "legal_acceptance_performed": False,
        "network_writes_performed": [],
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"http_status": status, "has_response": payload is not None, "error": error}))
    return 0 if status == 200 and isinstance(payload, Mapping) else 1


if __name__ == "__main__":
    raise SystemExit(main())
