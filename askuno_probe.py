#!/usr/bin/env python3
"""Read-only Askuno API discovery for covered-credit bounty work."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUT = Path(os.environ.get("ASKUNO_OUTPUT_FILE", "market-output/askuno.json"))
ENDPOINTS = {
    "agent_skill": "https://askuno.app/api/agent-skill",
    "bounties": "https://askuno.app/api/bounties/algora/available",
    "models": "https://askuno.app/api/models",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "User-Agent": "autonomous-income-runner-askuno-probe/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read(2_000_000)
            content_type = response.headers.get("content-type", "")
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return {
                "ok": True,
                "status": response.status,
                "content_type": content_type,
                "json": parsed,
                "text": None if parsed is not None else text,
            }
    except urllib.error.HTTPError as exc:
        text = exc.read(200_000).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        return {
            "ok": False,
            "status": exc.code,
            "content_type": exc.headers.get("content-type", ""),
            "json": parsed,
            "text": None if parsed is not None else text,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def main() -> int:
    report = {
        "generated_at": now_iso(),
        "endpoints": {name: fetch(url) for name, url in ENDPOINTS.items()},
    }
    atomic_write(OUTPUT, report)
    print(json.dumps({"ok": True, "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
