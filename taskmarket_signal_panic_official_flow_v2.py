#!/usr/bin/env python3
"""Compatibility wrapper for Taskmarket's description-only task payload.

The current public API identifies some bounty tasks in ``description`` instead of a
separate ``title`` field. The underlying fail-closed submission implementation remains
unchanged; this wrapper only normalizes that public response shape before validation.
"""
from __future__ import annotations

import argparse
from typing import Any, Mapping

import taskmarket_signal_panic_official_flow as core

_original_http_json = core.http_json


def _with_signal_panic_title(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    result = dict(payload)
    for key in ("task", "data"):
        nested = result.get(key)
        if isinstance(nested, Mapping):
            normalized = dict(nested)
            description = str(normalized.get("description") or "")
            if not normalized.get("title") and not normalized.get("name") and "signal panic" in description.lower():
                normalized["title"] = "Signal Panic"
            result[key] = normalized
            return result
    description = str(result.get("description") or "")
    if not result.get("title") and not result.get("name") and "signal panic" in description.lower():
        result["title"] = "Signal Panic"
    return result


def _patched_http_json(method: str, path_or_url: str, body: Mapping[str, Any] | None = None):
    status, payload, headers = _original_http_json(method, path_or_url, body)
    if method == "GET" and path_or_url == f"/api/tasks/{core.TASK_ID}" and status == 200:
        payload = _with_signal_panic_title(payload)
    return status, payload, headers


core.http_json = _patched_http_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "submit"))
    args = parser.parse_args()
    return core.prepare() if args.command == "prepare" else core.submit()


if __name__ == "__main__":
    raise SystemExit(main())
