#!/usr/bin/env python3
"""Rate-limit-aware launcher for the diversified AgentMart portfolio worker."""
from __future__ import annotations

import json
import threading
import time

import agentmart_portfolio as core

_LOCK = threading.Lock()
_LAST_REQUEST = 0.0
_MIN_INTERVAL = 4.0
_original_request_json = core.request_json
_original_upload_file = core.upload_file


def _pace() -> None:
    global _LAST_REQUEST
    with _LOCK:
        remaining = _MIN_INTERVAL - (time.time() - _LAST_REQUEST)
        if remaining > 0:
            time.sleep(remaining)
        _LAST_REQUEST = time.time()


def _is_rate_limited(exc: core.ApiError) -> bool:
    return exc.status == 429 or "rate limit" in json.dumps(exc.payload, ensure_ascii=False).lower()


def request_json(*args, **kwargs):
    kwargs["attempts"] = 1
    last = None
    for attempt in range(1, 9):
        _pace()
        try:
            return _original_request_json(*args, **kwargs)
        except core.ApiError as exc:
            last = exc
            if not _is_rate_limited(exc):
                raise
            time.sleep(min(120, 20 * attempt))
    raise last or RuntimeError("AgentMart request failed without an exception")


def upload_file(path, store_key):
    last = None
    for attempt in range(1, 7):
        _pace()
        try:
            return _original_upload_file(path, store_key)
        except core.ApiError as exc:
            last = exc
            if not _is_rate_limited(exc):
                raise
            time.sleep(min(120, 25 * attempt))
    raise last or RuntimeError("AgentMart upload failed without an exception")


core.request_json = request_json
core.upload_file = upload_file

if __name__ == "__main__":
    try:
        raise SystemExit(core.main())
    except Exception as exc:
        core.state["status"] = "failed"
        core.state["failed_at"] = core.now_iso()
        if isinstance(exc, core.ApiError):
            core.state["error"] = {
                "message": str(exc),
                "status": exc.status,
                "payload": core.sanitize(exc.payload),
            }
        else:
            core.state["error"] = core.sanitize(f"{type(exc).__name__}: {exc}")
        core.persist("Record rate-limit-aware AgentMart portfolio failure", True)
        raise
