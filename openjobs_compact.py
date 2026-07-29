#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path("openjobs-output/live.json")
OUTPUT = Path("openjobs-output/compact.json")


def unwrap(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "jobs", "items", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
            if isinstance(candidate, Mapping):
                for nested in ("jobs", "items", "results"):
                    nested_value = candidate.get(nested)
                    if isinstance(nested_value, list):
                        return [item for item in nested_value if isinstance(item, Mapping)]
    return []


def compact(item: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "title", "description", "status", "type", "jobType", "reward", "rewardAmount",
        "rewardToken", "currency", "budget", "skills", "requirements", "acceptanceCriteria",
        "deadline", "deadlineAt", "createdAt", "updatedAt", "escrow", "escrowStatus",
        "poster", "applicationsCount", "applicationCount", "isPaid", "paid", "paymentStatus",
    )
    return {key: item.get(key) for key in keys if item.get(key) is not None}


def main() -> int:
    value = json.loads(SOURCE.read_text(encoding="utf-8"))
    endpoints = value.get("endpoints", {}) if isinstance(value, Mapping) else {}
    jobs: dict[str, dict[str, Any]] = {}
    endpoint_summary = {}
    for name, response in endpoints.items():
        if not isinstance(response, Mapping):
            continue
        endpoint_summary[str(name)] = {
            "ok": response.get("ok"),
            "status": response.get("status"),
            "url": response.get("url"),
            "content_type": response.get("content_type"),
        }
        payload = response.get("payload")
        for item in unwrap(payload):
            entry = compact(item)
            identifier = str(entry.get("id") or json.dumps(entry, sort_keys=True))
            jobs[identifier] = entry

    skill = str((endpoints.get("skill") or {}).get("text_preview") or "")
    examples = []
    for index, line in enumerate(skill.splitlines()):
        if re.search(r"(?:curl|GET |POST |PATCH |DELETE ).*(?:openjobs\.bot/api|/api/)", line, re.I):
            examples.append({"line": index + 1, "text": line.strip()[:1200]})

    result = {
        "source_generated_at": value.get("generated_at") if isinstance(value, Mapping) else None,
        "endpoint_summary": endpoint_summary,
        "job_count": len(jobs),
        "jobs": list(jobs.values()),
        "api_examples": examples[:200],
        "skill_length": len(skill),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "jobs": len(jobs), "examples": len(examples)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
