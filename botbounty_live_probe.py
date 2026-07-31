#!/usr/bin/env python3
"""Read-only BotBounty live inventory and contract probe."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

API = "https://botbounty-production.up.railway.app/api"
SITE = "https://www.botbounty.ai"
OUTPUT = Path("market-output/botbounty-live.json")
SKILL = Path("market-output/botbounty-skill.md")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request(url: str, max_bytes: int = 4_000_000) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json,text/markdown,*/*", "User-Agent": "boundaryledger-botbounty-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read(max_bytes)
            text = raw.decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            return {"ok": True, "status": response.status, "url": response.geturl(), "content_type": response.headers.get("content-type", ""), "json": payload, "text": None if payload is not None else text, "bytes": len(raw)}
    except urllib.error.HTTPError as exc:
        raw = exc.read(500_000)
        text = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        return {"ok": False, "status": exc.code, "url": url, "json": payload, "text": None if payload is not None else text[:20_000], "bytes": len(raw)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def unwrap(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("bounties", "data", "items", "results"):
            if isinstance(value.get(key), list):
                return [dict(item) for item in value[key] if isinstance(item, Mapping)]
    return []


def compact_bounty(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "description": str(item.get("description") or "")[:3000],
        "category": item.get("category"),
        "reward": item.get("reward") or item.get("amount"),
        "currency": item.get("currency"),
        "status": item.get("status"),
        "funded": item.get("funded") or item.get("is_funded"),
        "deadline": item.get("deadline") or item.get("expires_at"),
        "acceptance_criteria": item.get("acceptance_criteria") or item.get("criteria"),
        "claimed_by": item.get("claimed_by") or item.get("solver_id"),
        "submission_count": item.get("submission_count") or item.get("submissions_count"),
    }


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    skill = request(SITE + "/skill.md")
    inventory = request(API + "/agent/bounties")
    bounties = unwrap(inventory.get("json"))
    details: dict[str, Any] = {}
    for item in bounties[:50]:
        bounty_id = item.get("id")
        if bounty_id is None:
            continue
        details[str(bounty_id)] = request(API + f"/agent/bounties/{bounty_id}", 1_000_000)
    skill_text = skill.get("text") if isinstance(skill.get("text"), str) else ""
    SKILL.parent.mkdir(parents=True, exist_ok=True)
    SKILL.write_text(skill_text or "BotBounty skill.md unavailable.\n", encoding="utf-8")
    report = {
        "generated_at": now_iso(),
        "writes_performed": [],
        "skill_status": {key: skill.get(key) for key in ("ok", "status", "url", "content_type", "bytes", "error") if skill.get(key) is not None},
        "inventory_status": {key: inventory.get(key) for key in ("ok", "status", "url", "content_type", "bytes", "error") if inventory.get(key) is not None},
        "bounty_count": len(bounties),
        "bounties": [compact_bounty(item) for item in bounties],
        "details": {key: {"ok": value.get("ok"), "status": value.get("status"), "json": value.get("json"), "error": value.get("error")} for key, value in details.items()},
    }
    atomic_write(OUTPUT, report)
    print(json.dumps({"ok": True, "bounties": len(bounties), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
