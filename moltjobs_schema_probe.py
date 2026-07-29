#!/usr/bin/env python3
"""Probe public MoltJobs API schema endpoints without authentication or mutation."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE = "https://api.moltjobs.io"
CANDIDATES = [
    "/docs-json",
    "/openapi.json",
    "/swagger.json",
    "/api-json",
    "/v1/docs-json",
    "/v1/openapi.json",
    "/v1/swagger.json",
    "/v1/api-json",
]
OUTPUT = Path(os.environ.get("MOLTJOBS_SCHEMA_OUTPUT", "moltjobs-output/schema-probe.json"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch(path: str) -> dict[str, Any]:
    url = BASE + path
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "nexaworks-schema-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(4_000_000).decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            try:
                payload: Any = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            result: dict[str, Any] = {
                "url": url,
                "status": response.status,
                "content_type": content_type,
                "bytes": len(raw.encode("utf-8")),
                "json": isinstance(payload, (dict, list)),
            }
            if isinstance(payload, Mapping):
                paths = payload.get("paths")
                if isinstance(paths, Mapping):
                    relevant = {}
                    for route, methods in paths.items():
                        lowered = str(route).lower()
                        if any(marker in lowered for marker in ("signup", "claim", "agent", "bid", "job")):
                            relevant[str(route)] = methods
                    result["relevant_paths"] = relevant
                    result["path_count"] = len(paths)
                else:
                    result["top_level_keys"] = sorted(str(key) for key in payload.keys())[:100]
            else:
                result["text_preview"] = raw[:500]
            return result
    except urllib.error.HTTPError as error:
        raw = error.read(2000).decode("utf-8", errors="replace")
        return {"url": url, "status": error.code, "error_preview": raw[:500]}
    except Exception as error:
        return {"url": url, "error": f"{type(error).__name__}: {error}"}


def main() -> int:
    output = {"generated_at": now_iso(), "probes": [fetch(path) for path in CANDIDATES]}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
