#!/usr/bin/env python3
"""Build a credential-free report from read-only Taskmarket CLI probe files."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUT = Path("taskmarket-output/cli-auth-probe.json")


def text(path: str, limit: int = 30000) -> str:
    value = Path(path)
    if not value.exists():
        return ""
    return value.read_text(encoding="utf-8", errors="replace")[:limit]


def json_file(path: str, default: Any) -> Any:
    value = Path(path)
    if not value.exists():
        return default
    return json.loads(value.read_text(encoding="utf-8", errors="strict"))


def scrub_text(value: str) -> str:
    value = re.sub(r"\beyJ[A-Za-z0-9._-]{20,}\b", "[REDACTED_JWT]", str(value))
    value = re.sub(
        r"\b(?:gh[pousr]|github_pat|sk|pk|api|token|secret)_[A-Za-z0-9._-]{16,}\b",
        "[REDACTED_TOKEN]",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"(?i)((?:authorization|api.?token|device.?encryption.?key)\s*[:=]\s*)[^\s,;}]+",
        r"\1[REDACTED]",
        value,
    )
    return value


def scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {str(key): scrub(item) for key, item in value.items()}
    return value


def exit_code(key: str) -> int:
    raw = text(f"/tmp/taskmarket-{key}.code", 20).strip()
    try:
        return int(raw)
    except ValueError:
        return 999


def main() -> int:
    package = scrub(json_file("/tmp/taskmarket-package.json", {}))
    npm_view = scrub(json_file("/tmp/taskmarket-npm-view.json", {}))
    contracts = scrub(json_file("/tmp/taskmarket-package-contracts.json", []))
    commands: dict[str, Any] = {}
    for key in ("help", "legal-help", "legal-status-json", "legal-status"):
        commands[key] = {
            "exit_code": exit_code(key),
            "stdout": scrub_text(text(f"/tmp/taskmarket-{key}.out")),
            "stderr": scrub_text(text(f"/tmp/taskmarket-{key}.err")),
        }

    report = {
        "schema_version": "taskmarket-cli-auth-probe-v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "package": package,
        "npm_distribution": npm_view,
        "commands": commands,
        "package_contract_match_count": len(contracts) if isinstance(contracts, list) else 0,
        "package_contract_matches": contracts,
        "network_writes_performed": [],
        "taskmarket_init_performed": False,
        "device_registration_performed": False,
        "legal_acceptance_performed": False,
        "wallet_created": False,
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "package_version": package.get("version") if isinstance(package, dict) else None,
        "legal_status_exit": commands["legal-status"]["exit_code"],
        "contract_matches": report["package_contract_match_count"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
