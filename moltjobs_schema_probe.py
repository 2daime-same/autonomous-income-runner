#!/usr/bin/env python3
"""Extract MoltJobs public API contracts relevant to earning, without mutation."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

URL = "https://api.moltjobs.io/docs-json"
OUTPUT = Path(os.environ.get("MOLTJOBS_SCHEMA_OUTPUT", "moltjobs-output/schema-probe.json"))
TARGET_ROUTES = {
    "/v1/agent-signups",
    "/v1/agent-signups/claim",
    "/v1/agents/{id}/api-keys",
    "/v1/agents/{id}/heartbeat",
    "/v1/jobs",
    "/v1/jobs/{id}",
    "/v1/public/jobs/{id}",
    "/v1/jobs/{jobId}/bids",
    "/v1/bids/allowance/{agentId}",
    "/v1/agents/{agentId}/wallet",
    "/v1/agents/{agentId}/wallet/provision",
    "/v1/agents/{agentId}/wallet/transactions",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_json() -> Mapping[str, Any]:
    request = urllib.request.Request(
        URL,
        headers={"Accept": "application/json", "User-Agent": "nexaworks-moltjobs-contract-probe/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(5_000_000).decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    if not isinstance(payload, Mapping):
        raise RuntimeError("Unexpected OpenAPI response")
    return payload


def schema_name(ref: str) -> str | None:
    prefix = "#/components/schemas/"
    return ref[len(prefix):] if ref.startswith(prefix) else None


def referenced_schema_names(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        ref = value.get("$ref")
        if isinstance(ref, str):
            name = schema_name(ref)
            if name:
                found.add(name)
        for item in value.values():
            found.update(referenced_schema_names(item))
    elif isinstance(value, list):
        for item in value:
            found.update(referenced_schema_names(item))
    return found


def main() -> int:
    payload = get_json()
    paths = payload.get("paths")
    components = payload.get("components")
    schemas = components.get("schemas") if isinstance(components, Mapping) else None
    if not isinstance(paths, Mapping) or not isinstance(schemas, Mapping):
        raise RuntimeError("OpenAPI paths/components missing")

    selected_paths = {route: paths[route] for route in sorted(TARGET_ROUTES) if route in paths}
    pending = referenced_schema_names(selected_paths)
    selected_schemas: dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in selected_schemas:
            continue
        schema = schemas.get(name)
        if schema is None:
            continue
        selected_schemas[name] = schema
        pending.update(referenced_schema_names(schema) - selected_schemas.keys())

    output = {
        "generated_at": now_iso(),
        "source": URL,
        "source_info": payload.get("info"),
        "security_schemes": components.get("securitySchemes") if isinstance(components, Mapping) else None,
        "selected_paths": selected_paths,
        "selected_schemas": {name: selected_schemas[name] for name in sorted(selected_schemas)},
        "missing_target_routes": sorted(TARGET_ROUTES - selected_paths.keys()),
        "writes_performed": [],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "paths": len(selected_paths), "schemas": len(selected_schemas)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())