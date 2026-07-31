#!/usr/bin/env python3
"""Read the public Callboard capability taxonomy and active job types."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path("market-output/callboard-taxonomy.json")
BASE = "https://api.getcallboard.com"
URLS = [
    "/capabilities",
    "/capabilities/tags?query=research",
    "/capabilities/tags?query=code",
    "/capabilities/tags?query=data",
    "/capabilities/tags?query=writing",
    "/capabilities/tags?query=testing",
    "/api/v2/job-types",
]


def fetch(path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        BASE + path,
        headers={"Accept": "application/json", "User-Agent": "autonomous-income-runner-callboard-taxonomy/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            text = response.read(4_000_000).decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(text)
            except json.JSONDecodeError:
                payload = {"text_preview": text[:3000]}
            return {"status": response.status, "content_type": response.headers.get("content-type", ""), "payload": payload}
    except urllib.error.HTTPError as error:
        text = error.read(500_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"text_preview": text[:3000]}
        return {"status": error.code, "content_type": error.headers.get("content-type", ""), "payload": payload}


def collect_tags(value: Any) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, Mapping):
            return
        slug = item.get("slug") or item.get("key")
        name = item.get("name") or item.get("displayName")
        identifier = item.get("id")
        if isinstance(slug, str) and (isinstance(name, str) or isinstance(identifier, str)):
            found[slug] = {
                "id": identifier,
                "slug": slug,
                "name": name,
                "description": str(item.get("description") or "")[:1000],
                "active": item.get("active"),
                "category_id": item.get("categoryId") or item.get("category_id"),
            }
        for child in item.values():
            visit(child)
    visit(value)
    return sorted(found.values(), key=lambda item: str(item.get("slug") or ""))


def compact_job_types(value: Any) -> list[dict[str, Any]]:
    items = value.get("jobTypes") if isinstance(value, Mapping) else None
    if not isinstance(items, list):
        return []
    return [
        {
            "id": item.get("id"),
            "key": item.get("key"),
            "display_name": item.get("displayName"),
            "description": str(item.get("description") or "")[:1200],
            "active": item.get("active"),
            "capability_tag_id": item.get("capabilityTagId"),
            "artifact_required": (item.get("artifactSchemaJson") or {}).get("required") if isinstance(item.get("artifactSchemaJson"), Mapping) else None,
        }
        for item in items
        if isinstance(item, Mapping)
    ]


def main() -> int:
    results = {path: fetch(path) for path in URLS}
    tags: dict[str, dict[str, Any]] = {}
    for path, result in results.items():
        if "/capabilities" not in path:
            continue
        for item in collect_tags(result.get("payload")):
            tags[str(item["slug"])] = item
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "writes_performed": [],
        "endpoints": {path: {"status": result.get("status"), "content_type": result.get("content_type")} for path, result in results.items()},
        "capability_tags": sorted(tags.values(), key=lambda item: str(item.get("slug") or "")),
        "job_types": compact_job_types(results.get("/api/v2/job-types", {}).get("payload")),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "tags": len(report["capability_tags"]), "job_types": len(report["job_types"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
