#!/usr/bin/env python3
"""Extract only top-level request/response fields for the Callboard worker loop."""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

URL = "https://api.getcallboard.com/openapi.json"
OUTPUT = Path("market-output/callboard-worker-contract.json")
EXACT_PATHS = {
    "/api/v2/agents/register",
    "/api/v2/agents/me",
    "/api/v2/agents/me/claim-link",
    "/api/v2/agents/me/heartbeat",
    "/api/v2/agents/me/starter-job",
    "/api/v2/agents/me/setup-links",
    "/api/v2/home",
    "/api/v2/jobs",
    "/api/v2/jobs/search",
    "/api/v2/jobs/{id}",
    "/api/v2/jobs/{id}/applications",
    "/api/v2/worker-agents/me/applications",
    "/api/v2/worker-agents/me/participation-slots",
    "/api/v2/participation-slots/{slotId}/acknowledge",
    "/api/v2/participation-slots/{slotId}/submit",
    "/api/v2/participation-slots/{slotId}/uploads",
    "/api/v2/uploads/{uploadId}/complete",
    "/api/v2/submissions/{id}/status",
}


def fetch() -> Mapping[str, Any]:
    request = urllib.request.Request(URL, headers={"Accept": "application/json", "User-Agent": "callboard-compact-contract/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        value = json.loads(response.read(12_000_000).decode("utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("OpenAPI root is not an object")
    return value


def resolve(document: Mapping[str, Any], value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, Mapping) or not isinstance(value.get("$ref"), str):
        return value, None
    ref = value["$ref"]
    if not ref.startswith("#/"):
        return value, ref
    current: Any = document
    for segment in ref[2:].split("/"):
        current = current.get(segment.replace("~1", "/").replace("~0", "~")) if isinstance(current, Mapping) else None
    return (current if current is not None else value), ref


def shape(document: Mapping[str, Any], schema: Any, depth: int = 0) -> Any:
    schema, ref = resolve(document, schema)
    if not isinstance(schema, Mapping):
        return schema
    output: dict[str, Any] = {}
    if ref:
        output["ref"] = ref
    for key in ("type", "format", "enum", "required", "description"):
        if key in schema:
            value = schema[key]
            output[key] = value[:1000] if isinstance(value, str) else value
    if depth >= 2:
        return output
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        output["properties"] = {
            str(name): shape(document, child, depth + 1)
            for name, child in list(properties.items())[:100]
        }
    if "items" in schema:
        output["items"] = shape(document, schema.get("items"), depth + 1)
    for key in ("oneOf", "anyOf", "allOf"):
        if isinstance(schema.get(key), list):
            output[key] = [shape(document, item, depth + 1) for item in schema[key][:10]]
    return output


def media(document: Mapping[str, Any], content: Any) -> dict[str, Any]:
    if not isinstance(content, Mapping):
        return {}
    return {
        str(media_type): shape(document, item.get("schema"))
        for media_type, item in content.items()
        if isinstance(item, Mapping)
    }


def operation(document: Mapping[str, Any], op: Mapping[str, Any]) -> dict[str, Any]:
    request_body, request_ref = resolve(document, op.get("requestBody"))
    request_shape = None
    if isinstance(request_body, Mapping):
        request_shape = {
            "ref": request_ref,
            "required": request_body.get("required"),
            "content": media(document, request_body.get("content")),
        }
    responses = {}
    for code, response in (op.get("responses") or {}).items():
        response, response_ref = resolve(document, response)
        responses[str(code)] = {
            "ref": response_ref,
            "description": str(response.get("description") or "")[:1000] if isinstance(response, Mapping) else "",
            "content": media(document, response.get("content")) if isinstance(response, Mapping) else {},
        }
    return {
        "operation_id": op.get("operationId"),
        "description": str(op.get("description") or "")[:3000],
        "security": op.get("security"),
        "parameters": [
            {
                "name": (resolve(document, parameter)[0] or {}).get("name") if isinstance(resolve(document, parameter)[0], Mapping) else None,
                "in": (resolve(document, parameter)[0] or {}).get("in") if isinstance(resolve(document, parameter)[0], Mapping) else None,
                "required": (resolve(document, parameter)[0] or {}).get("required") if isinstance(resolve(document, parameter)[0], Mapping) else None,
                "schema": shape(document, (resolve(document, parameter)[0] or {}).get("schema")) if isinstance(resolve(document, parameter)[0], Mapping) else None,
            }
            for parameter in (op.get("parameters") or [])
        ],
        "request": request_shape,
        "responses": responses,
    }


def main() -> int:
    document = fetch()
    paths = document.get("paths") if isinstance(document.get("paths"), Mapping) else {}
    selected = {}
    missing = []
    for path in sorted(EXACT_PATHS):
        item = paths.get(path)
        if not isinstance(item, Mapping):
            missing.append(path)
            continue
        selected[path] = {
            method.upper(): operation(document, op)
            for method, op in item.items()
            if method.lower() in {"get", "post", "patch", "put", "delete"} and isinstance(op, Mapping)
        }
    related_paths = sorted(
        str(path)
        for path in paths
        if any(term in str(path) for term in ("heartbeat", "setup-links", "uploads", "starter-job"))
    )
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": URL,
        "writes_performed": [],
        "security_schemes": ((document.get("components") or {}).get("securitySchemes") or {}),
        "paths": selected,
        "missing_exact_paths": missing,
        "related_paths": related_paths,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "selected": len(selected), "missing": missing, "related": related_paths}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
