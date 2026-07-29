#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

SOURCE = Path("openjobs-output/live.json")
OUTPUT = Path("openjobs-output/actionable.txt")


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


def status_of(item: Mapping[str, Any]) -> str:
    return str(item.get("status") or item.get("state") or "unknown").strip().lower()


def safe_value(value: Any, limit: int = 800) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return text.replace("\n", " ")[:limit]


def main() -> int:
    value = json.loads(SOURCE.read_text(encoding="utf-8"))
    endpoints = value.get("endpoints", {})
    unique: dict[str, Mapping[str, Any]] = {}
    observations: dict[str, set[str]] = {}
    for source in ("jobs_default", "jobs_open_lower", "jobs_open_upper"):
        response = endpoints.get(source) or {}
        for item in unwrap(response.get("payload")):
            identifier = str(item.get("id") or json.dumps(item, sort_keys=True))
            unique[identifier] = item
            observations.setdefault(identifier, set()).add(source)

    counts = Counter(status_of(item) for item in unique.values())
    terminal = {"cancelled", "canceled", "completed", "closed", "rejected", "expired", "paid"}
    candidates = [item for item in unique.values() if status_of(item) not in terminal]
    candidates.sort(
        key=lambda item: (
            str(item.get("createdAt") or item.get("created_at") or ""),
            str(item.get("updatedAt") or item.get("updated_at") or ""),
        ),
        reverse=True,
    )

    lines = [
        "status_counts=" + json.dumps(dict(sorted(counts.items())), ensure_ascii=False),
        f"nonterminal_count={len(candidates)}",
    ]
    for index, item in enumerate(candidates[:50], start=1):
        selected = {}
        for key, raw in item.items():
            lower = str(key).lower()
            if lower in {
                "id", "title", "description", "status", "state", "type", "jobtype", "job_type",
                "reward", "rewardamount", "reward_amount", "rewardtoken", "reward_token", "currency",
                "budget", "amount", "wageamount", "wage_amount", "payment", "paid", "ispaid", "is_paid",
                "escrow", "escrowstatus", "escrow_status", "deadline", "deadlineat", "deadline_at",
                "skills", "requirements", "acceptancecriteria", "acceptance_criteria", "applicationscount",
                "application_count", "createdat", "created_at", "updatedat", "updated_at", "poster",
            }:
                selected[str(key)] = safe_value(raw)
        selected["observed_via"] = ",".join(sorted(observations.get(str(item.get("id")), set())))
        selected["all_top_level_keys"] = ",".join(sorted(str(key) for key in item.keys()))
        lines.append(f"candidate_{index}=" + json.dumps(selected, ensure_ascii=False, sort_keys=True))

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "statuses": counts, "nonterminal": len(candidates)}, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
