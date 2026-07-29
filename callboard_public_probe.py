#!/usr/bin/env python3
"""Read Callboard's public opportunity inventory without registration or auth."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path(os.environ.get("CALLBOARD_PUBLIC_OUTPUT", "market-output/callboard-public.json"))
ENDPOINTS = [
    "https://api.getcallboard.com/api/v1/calls?status=open",
    "https://api.getcallboard.com/api/v1/calls",
    "https://api.getcallboard.com/api/v1/stats",
]
SECRET = re.compile(r"(?i)(api[_-]?key|authorization|bearer|token|secret|private[_-]?key|claim[_-]?code)")


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): ("[REDACTED]" if SECRET.search(str(k)) else sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\b(?:sk|pk|api|key|token)_[A-Za-z0-9_-]{16,}\b", "[REDACTED]", value)
        value = re.sub(r"\b0x[a-fA-F0-9]{64}\b", "[REDACTED_HEX]", value)
        return value[:12000]
    return value


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "nexaworks-callboard-readonly-probe/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else None
            return {"ok": True, "status": response.status, "url": response.geturl(), "payload": sanitize(payload)}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw[:5000]
        return {"ok": False, "status": exc.code, "url": url, "payload": sanitize(payload)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def unwrap(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "items", "calls", "opportunities", "jobs", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
            if isinstance(candidate, Mapping):
                nested = unwrap(candidate)
                if nested:
                    return nested
    return []


def main() -> int:
    endpoints = [fetch(url) for url in ENDPOINTS]
    calls: list[Mapping[str, Any]] = []
    for result in endpoints:
        calls.extend(unwrap((result.get("payload") or {})))
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "safety": "GET-only; no registration, terms acceptance, signature, application, submission, payment, or withdrawal",
        "endpoint_results": endpoints,
        "observed_call_records": len(calls),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"ok": True, "records": len(calls)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
