#!/usr/bin/env python3
"""Compact all Callboard routes needed for registration, starter work, paid jobs, and payout setup.

Read-only. It persists no credentials and performs no mutations.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

URL = "https://api.getcallboard.com/openapi.json"
OUTPUT = Path("market-output/callboard-routes.json")
PATH_MARKERS = (
    "/agents/register",
    "/agents/me",
    "/home",
    "/heartbeat",
    "/jobs",
    "/applications",
    "/participation-slots",
    "/submissions",
    "/uploads",
    "/setup-links",
    "/starter-job",
)


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "autonomous-income-runner-callboard-openapi/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read(12_000_000).decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read(500_000).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {body[:1000]}") from error


def resolve(document: Mapping[str, Any], value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, Mapping) or not isinstance(value.get("$ref"), str):
        return value, None
    ref = value["$ref"]
    if not ref.startswith("#/"):
        return value, ref
    current: Any = document
    for segment in ref[2:].split("/"):
        if not isinstance(current, Mapping):
            return value, ref
        current = current.get(segment.replace("~1", "/").replace("~0", "~"))
    return (current if current is not None else value), ref


def compact_schema(document: Mapping[str, Any], schema: Any, depth: int = 0) -> Any:
    schema, source_ref = resolve(document, schema)
    if not isinstance(schema, Mapping):
        return schema
    if depth >= 6:
        return {"source_ref": source_ref, "truncated": True} if source_ref else {"truncated": True}
    output: dict[str, Any] = {}
    if source_ref:
        output["source_ref"] = source_ref
    for key in (
        "type", "format", "description", "enum", "required", "default",
        "minimum", "maximum", "minLength", "maxLength", "nullable",
    ):
        if key in schema:
            value = schema[key]
            output[key] = value[:2000] if isinstance(value, str) else value
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        output["properties"] = {
            str(name): compact_schema(document, child, depth + 1)
            for name, child in list(properties.items())[:120]
        }
    if "items" in schema:
        output["items"] = compact_schema(document, schema.get("items"), depth + 1)
    for key in ("oneOf", "anyOf", "allOf"):
        values = schema.get(key)
        if isinstance(values, list):
            output[key] = [compact_schema(document, item, depth + 1) for item in values[:20]]
    if "additionalProperties" in schema:
        output["additionalProperties"] = compact_schema(document, schema.get("additionalProperties"), depth + 1)
    return output


def media_schemas(document: Mapping[str, Any], content: Any) -> dict[str, Any]:
    if not isinstance(content, Mapping):
        return {}
    output: dict[str, Any] = {}
    for media_type, item in list(content.items())[:20]:
        if not isinstance(item, Mapping):
            continue
        output[str(media_type)] = compact_schema(document, item.get("schema"))
    return output


def compact_parameter(document: Mapping[str, Any], parameter: Any) -> dict[str, Any]:
    parameter, source_ref = resolve(document, parameter)
    if not isinstance(parameter, Mapping):
        return {"unparsed": True}
    output = {
        "name": parameter.get("name"),
        "in": parameter.get("in"),
        "required": parameter.get("required"),
        "description": str(parameter.get("description") or "")[:1200],
        "schema": compact_schema(document, parameter.get("schema")),
    }
    if source_ref:
        output["source_ref"] = source_ref
    return output


def compact_operation(document: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[str, Any]:
    request_body, request_ref = resolve(document, operation.get("requestBody"))
    request_content = request_body.get("content") if isinstance(request_body, Mapping) else None
    responses: dict[str, Any] = {}
    for status, response in (operation.get("responses") or {}).items():
        response, response_ref = resolve(document, response)
        if not isinstance(response, Mapping):
            responses[str(status)] = {"unparsed": True}
            continue
        item: dict[str, Any] = {
            "description": str(response.get("description") or "")[:1500],
            "content": media_schemas(document, response.get("content")),
        }
        if response_ref:
            item["source_ref"] = response_ref
        responses[str(status)] = item
    output: dict[str, Any] = {
        "operation_id": operation.get("operationId"),
        "summary": operation.get("summary"),
        "description": str(operation.get("description") or "")[:5000],
        "security": operation.get("security"),
        "parameters": [compact_parameter(document, item) for item in (operation.get("parameters") or [])],
        "request": {
            "required": request_body.get("required") if isinstance(request_body, Mapping) else None,
            "content": media_schemas(document, request_content),
        } if request_body is not None else None,
        "responses": responses,
    }
    if request_ref:
        output["request"]["source_ref"] = request_ref
    return output


def main() -> int:
    document = fetch_json(URL)
    if not isinstance(document, Mapping):
        raise RuntimeError("OpenAPI document is not an object")
    selected: dict[str, Any] = {}
    for path, path_item in (document.get("paths") or {}).items():
        if not any(marker in str(path) for marker in PATH_MARKERS):
            continue
        if not isinstance(path_item, Mapping):
            continue
        operations = {
            method.upper(): compact_operation(document, operation)
            for method, operation in path_item.items()
            if method.lower() in {"get", "post", "put", "patch", "delete"}
            and isinstance(operation, Mapping)
        }
        if operations:
            selected[str(path)] = operations
    security_schemes = ((document.get("components") or {}).get("securitySchemes") or {})
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": URL,
        "writes_performed": [],
        "security_schemes": security_schemes,
        "selected_path_count": len(selected),
        "paths": selected,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "paths": len(selected), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
