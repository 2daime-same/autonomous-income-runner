#!/usr/bin/env python3
"""Extract a compact, reviewable AgentJob runtime contract from the inspected npm package."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path(os.environ.get("AGENTJOB_PACKAGE_EVIDENCE", "market-output/agentjob-package.json"))
OUTPUT = Path(os.environ.get("AGENTJOB_CONTRACT_OUTPUT", "market-output/agentjob-contract.json"))
KEYWORDS = (
    "fetch(",
    "callTool(",
    "register",
    "apiKey",
    "wallet",
    "price",
    "rate",
    "profile",
    "service",
    "get_next_task",
    "submit_response",
    "get_my_profile",
    "heartbeat",
    "runDaemon",
    "startBridge",
    "export ",
    "process.env.",
    "/api/",
    "tools/list",
    "tools/call",
    "StreamableHTTP",
)
SECRET_RE = re.compile(r"\b(?:ak|aj|agentjob)_(?:live|test)?[A-Za-z0-9_-]{8,}", re.I)
URL_RE = re.compile(r"https?://[^\s'\"`)}]+")
TOOL_RE = re.compile(r"callTool\([^,]+,\s*['\"]([^'\"]+)['\"]")
ENV_RE = re.compile(r"process\.env\.([A-Z0-9_]+)")
EXPORT_RE = re.compile(r"\bexport\s+(?:async\s+)?(?:function|const|class)\s+([A-Za-z_$][\w$]*)")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    sources = data.get("selected_sources") if isinstance(data, Mapping) else None
    if not isinstance(sources, Mapping):
        raise RuntimeError("selected_sources missing from AgentJob package evidence")

    files: dict[str, Any] = {}
    all_tools: set[str] = set()
    all_env: set[str] = set()
    all_urls: set[str] = set()
    all_exports: set[str] = set()
    for path, raw in sources.items():
        if not isinstance(raw, str):
            continue
        text = SECRET_RE.sub("[REDACTED]", raw)
        lines = text.splitlines()
        selected_lines = []
        for index, line in enumerate(lines, 1):
            if any(keyword.lower() in line.lower() for keyword in KEYWORDS):
                selected_lines.append({"line": index, "text": line[:1000]})
        tools = sorted(set(TOOL_RE.findall(text)))
        env = sorted(set(ENV_RE.findall(text)))
        urls = sorted(set(URL_RE.findall(text)))
        exports = sorted(set(EXPORT_RE.findall(text)))
        all_tools.update(tools)
        all_env.update(env)
        all_urls.update(urls)
        all_exports.update(exports)
        files[str(path)] = {
            "line_count": len(lines),
            "tools": tools,
            "environment_variables": env,
            "urls": urls,
            "exports": exports,
            "selected_lines": selected_lines[:300],
        }

    result = {
        "generated_at": now_iso(),
        "package": data.get("package"),
        "version": data.get("version"),
        "tools": sorted(all_tools),
        "environment_variables": sorted(all_env),
        "urls": sorted(all_urls),
        "exports": sorted(all_exports),
        "files": files,
        "execution_performed": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"ok": True, "tools": len(all_tools), "exports": len(all_exports)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())