#!/usr/bin/env python3
"""Create one truthful MoltJobs agent-signup request.

The endpoint sends a claim link to the authorized account email. This script does
not accept terms, create a wallet, buy bid credits, place a bid, or submit work.
It writes only a sanitized receipt; any claim token remains in Gmail.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

URL = "https://api.moltjobs.io/v1/agent-signups"
OUTPUT = Path(os.environ.get("MOLTJOBS_SIGNUP_OUTPUT", "moltjobs-output/signup.json"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in {"token", "claim_token", "claimtoken", "api_key", "apikey", "rawkey", "secret"}:
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\bmj_(?:live|test)_[A-Za-z0-9_-]+", "[REDACTED]", value)
        value = re.sub(r"(?i)(claim[/_-])([A-Za-z0-9_-]{16,})", r"\1[REDACTED]", value)
    return value


def main() -> int:
    payload = {
        "agentHandle": "boundaryledger-agent-jp",
        "name": "BoundaryLedger Agent",
        "vertical": "RESEARCH",
        "ownerEmail": "2daimesame@gmail.com",
    }
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "nexaworks-autonomous-income-runner/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw else None
            result = {
                "ok": True,
                "status": response.status,
                "requested_at": now_iso(),
                "request": {**payload, "ownerEmail": "2d***@gmail.com"},
                "response": sanitize(body),
                "human_steps_not_performed": ["claim_link", "terms_acceptance", "wallet_setup", "bid_purchase"],
            }
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw)
        except json.JSONDecodeError:
            body = raw[:5000]
        result = {
            "ok": False,
            "status": error.code,
            "requested_at": now_iso(),
            "request": {**payload, "ownerEmail": "2d***@gmail.com"},
            "response": sanitize(body),
        }
    except Exception as error:
        result = {
            "ok": False,
            "requested_at": now_iso(),
            "request": {**payload, "ownerEmail": "2d***@gmail.com"},
            "error": f"{type(error).__name__}: {error}",
        }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result.get("ok"), "status": result.get("status")}))
    return 0 if result.get("ok") or result.get("status") == 409 else 1


if __name__ == "__main__":
    raise SystemExit(main())
