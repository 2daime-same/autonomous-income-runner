#!/usr/bin/env python3
"""Reduce the verbose public marketplace probe into a reviewable index."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

INPUT = Path(os.environ.get("PUBLIC_BOUNTY_SITE_INPUT", "market-output/public-bounty-sites.json"))
OUTPUT = Path(os.environ.get("PUBLIC_BOUNTY_SITE_INDEX", "market-output/public-bounty-sites-summary.json"))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def compact_endpoint(endpoint: Mapping[str, Any]) -> dict[str, Any]:
    summary = endpoint.get("json_summary")
    compact: dict[str, Any] = {
        "url": endpoint.get("url"),
        "status": endpoint.get("status"),
        "ok": endpoint.get("ok"),
        "content_type": endpoint.get("content_type"),
    }
    if isinstance(summary, Mapping):
        compact["shape"] = summary.get("shape")
        compact["keys"] = summary.get("keys")
        for key, value in summary.items():
            if key.endswith("_count") or key in {"count", "total", "next", "next_cursor"}:
                compact[key] = value
        if isinstance(summary.get("sample"), Mapping):
            compact["sample_keys"] = list(summary["sample"])[:50]
        for key, value in summary.items():
            if key.endswith("_sample") and isinstance(value, list):
                compact[f"{key}_item_keys"] = [
                    list(item)[:50] if isinstance(item, Mapping) else type(item).__name__
                    for item in value[:5]
                ]
    if endpoint.get("text_preview"):
        compact["text_preview"] = str(endpoint["text_preview"])[:800]
    if endpoint.get("error"):
        compact["error"] = endpoint.get("error")
    return compact


def main() -> int:
    source = read_json(INPUT)
    output: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_generated_at": source.get("generated_at"),
        "sites": {},
    }
    sites = source.get("sites")
    if not isinstance(sites, Mapping):
        raise ValueError("Input has no sites object")
    for name, wrapper in sites.items():
        result = wrapper.get("result") if isinstance(wrapper, Mapping) else None
        if not isinstance(result, Mapping):
            output["sites"][str(name)] = {
                "ok": False,
                "error": wrapper.get("error") if isinstance(wrapper, Mapping) else "invalid wrapper",
            }
            continue
        endpoint_results = result.get("endpoint_results")
        endpoint_index: list[dict[str, Any]] = []
        if isinstance(endpoint_results, Mapping):
            for _, endpoint in endpoint_results.items():
                if not isinstance(endpoint, Mapping):
                    continue
                # Keep JSON responses, successful responses, and non-404 failures.
                if (
                    endpoint.get("json_summary") is not None
                    or endpoint.get("ok") is True
                    or endpoint.get("status") not in (None, 404)
                ):
                    endpoint_index.append(compact_endpoint(endpoint))
        endpoint_index.sort(
            key=lambda item: (
                0 if item.get("ok") else 1,
                int(item.get("status") or 999),
                str(item.get("url")),
            )
        )
        output["sites"][str(name)] = {
            "ok": wrapper.get("ok") if isinstance(wrapper, Mapping) else None,
            "origin": result.get("origin"),
            "summary": result.get("summary"),
            "github_issue_urls": result.get("github_issue_urls", [])[:300],
            "candidate_api_urls": result.get("candidate_api_urls", [])[:300],
            "endpoint_index": endpoint_index[:150],
        }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temp.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(OUTPUT),
                "sites": {
                    name: {
                        "issues": len(value.get("github_issue_urls", [])),
                        "endpoints": len(value.get("endpoint_index", [])),
                    }
                    for name, value in output["sites"].items()
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
