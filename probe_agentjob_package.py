#!/usr/bin/env python3
"""Inspect the published AgentJob npm package without executing third-party code."""
from __future__ import annotations

import io
import json
import os
import re
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REGISTRY = "https://registry.npmjs.org/agentjob/latest"
OUTPUT = Path(os.environ.get("AGENTJOB_PROBE_OUTPUT", "market-output/agentjob-package.json"))
MAX_TARBALL = 15_000_000
MAX_FILE = 1_000_000
NEEDLES = (
    "agent-job.ai",
    "/api/",
    "register",
    "api key",
    "api_key",
    "get_next_task",
    "submit_response",
    "heartbeat",
    "price",
    "wallet",
    "withdraw",
    "task square",
)
SECRET_RE = re.compile(r"\b(?:aj|agentjob)_(?:live|test)_[A-Za-z0-9_-]+", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "nexaworks-agentjob-probe/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        value = json.loads(response.read(3_000_000).decode("utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("Unexpected npm registry response")
    return value


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "nexaworks-agentjob-probe/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_TARBALL + 1)
    if len(data) > MAX_TARBALL:
        raise RuntimeError("Package tarball exceeds inspection limit")
    return data


def safe_text(raw: bytes) -> str | None:
    if b"\x00" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    meta = fetch_json(REGISTRY)
    dist = meta.get("dist") if isinstance(meta.get("dist"), Mapping) else {}
    tarball = str(dist.get("tarball") or "")
    if not tarball.startswith("https://"):
        raise RuntimeError("Missing HTTPS tarball URL")
    data = fetch_bytes(tarball)

    files: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.size > MAX_FILE:
                continue
            normalized = Path(member.name)
            if normalized.is_absolute() or ".." in normalized.parts:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read(MAX_FILE + 1)
            text = safe_text(raw)
            files.append({"path": member.name, "size": member.size})
            if text is None:
                continue
            lower = text.lower()
            for needle in NEEDLES:
                start = 0
                while True:
                    index = lower.find(needle, start)
                    if index < 0:
                        break
                    left = max(0, index - 220)
                    right = min(len(text), index + len(needle) + 420)
                    snippet = SECRET_RE.sub("[REDACTED]", text[left:right])
                    matches.append({"path": member.name, "needle": needle, "snippet": snippet})
                    start = index + len(needle)
                    if len(matches) >= 250:
                        break
                if len(matches) >= 250:
                    break
            if len(matches) >= 250:
                break

    result = {
        "generated_at": now_iso(),
        "registry": REGISTRY,
        "package": meta.get("name"),
        "version": meta.get("version"),
        "description": meta.get("description"),
        "homepage": meta.get("homepage"),
        "repository": meta.get("repository"),
        "bin": meta.get("bin"),
        "dist_integrity": dist.get("integrity"),
        "tarball_bytes": len(data),
        "inspected_file_count": len(files),
        "files": files[:300],
        "matches": matches,
        "execution_performed": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "version": meta.get("version"), "matches": len(matches)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())