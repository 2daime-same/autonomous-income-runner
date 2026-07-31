#!/usr/bin/env python3
"""Fetch and compact the official Callboard machine onboarding contract.

Read-only: no registration, application, claim, payment, or submission.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path("market-output/callboard-contract.json")
URLS = {
    "skill": "https://getcallboard.com/skill.md",
    "openapi": "https://api.getcallboard.com/openapi.json",
    "capabilities": "https://api.getcallboard.com/api/v2/capabilities",
    "tags": "https://api.getcallboard.com/api/v2/capabilities/tags?query=research",
    "job_types": "https://api.getcallboard.com/api/v2/job-types",
}
TARGETS = [
    "/api/v2/agents/register",
    "/api/v2/agents/me",
    "/api/v2/agents/me/claim-link",
    "/api/v2/agents/me/starter-job",
    "/api/v2/agents/me/setup-links",
    "/api/v2/jobs",
    "/api/v2/jobs/search",
    "/api/v2/jobs/{id}",
    "/api/v2/jobs/{id}/applications",
    "/api/v2/worker-agents/me/applications",
    "/api/v2/worker-agents/me/participation-slots",
    "/api/v2/participation-slots/{slotId}/acknowledge",
    "/api/v2/participation-slots/{slotId}/submit",
    "/api/v2/submissions/{id}/status",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch(url: str, accept: str) -> tuple[int, str, str]:
    request = urllib.request.Request(
        url,
        headers={"Accept": accept, "User-Agent": "autonomous-income-runner-callboard-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read(8_000_000)
            return response.status, response.headers.get("content-type", ""), raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("content-type", ""), error.read(500_000).decode("utf-8", errors="replace")


def resolve_ref(document: Mapping[str, Any], value: Any) -> Any:
    if not isinstance(value, Mapping) or "$ref" not in value:
        return value
    ref = str(value["$ref"])
    if not ref.startswith("#/"):
        return value
    current: Any = document
    for segment in ref[2:].split("/"):
        if not isinstance(current, Mapping):
            return value
        current = current.get(segment.replace("~1", "/").replace("~0", "~"))
    return current if current is not None else value


def compact_schema(document: Mapping[str, Any], schema: Any, depth: int = 0) -> Any:
    schema = resolve_ref(document, schema)
    if depth >= 5 or not isinstance(schema, Mapping):
        return schema if not isinstance(schema, (dict, list)) else f"<{type(schema).__name__}>"
    output: dict[str, Any] = {}
    for key in ("type", "format", "description", "enum", "required", "default", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
        if key in schema:
            value = schema[key]
            output[key] = value[:1000] if isinstance(value, str) else value
    if "properties" in schema and isinstance(schema["properties"], Mapping):
        output["properties"] = {
            str(name): compact_schema(document, child, depth + 1)
            for name, child in list(schema["properties"].items())[:80]
        }
    if "items" in schema:
        output["items"] = compact_schema(document, schema["items"], depth + 1)
    for key in ("oneOf", "anyOf", "allOf"):
        if isinstance(schema.get(key), list):
            output[key] = [compact_schema(document, item, depth + 1) for item in schema[key][:10]]
    if "$ref" in schema:
        output["source_ref"] = schema["$ref"]
    return output


def compact_operation(document: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[str, Any]:
    request_body = operation.get("requestBody")
    request_body = resolve_ref(document, request_body)
    body_schema = None
    if isinstance(request_body, Mapping):
        content = request_body.get("content")
        if isinstance(content, Mapping):
            for content_type in ("application/json", "multipart/form-data", "application/octet-stream"):
                item = content.get(content_type)
                if isinstance(item, Mapping):
                    body_schema = compact_schema(document, item.get("schema"))
                    break
    parameters = []
    for parameter in operation.get("parameters") or []:
        parameter = resolve_ref(document, parameter)
        if not isinstance(parameter, Mapping):
            continue
        parameters.append(
            {
                "name": parameter.get("name"),
                "in": parameter.get("in"),
                "required": parameter.get("required"),
                "schema": compact_schema(document, parameter.get("schema")),
            }
        )
    return {
        "summary": operation.get("summary"),
        "description": str(operation.get("description") or "")[:3000],
        "operation_id": operation.get("operationId"),
        "security": operation.get("security"),
        "parameters": parameters,
        "request_body": body_schema,
        "response_codes": sorted((operation.get("responses") or {}).keys()),
    }


def snippets(text: str) -> list[dict[str, str]]:
    needles = [
        "Machine Checklist",
        "agents/register",
        "starter-job",
        "claimUrl",
        "payout",
        "Participation Slot",
        "acknowledge",
        "submit",
        "paid jobs",
    ]
    lower = text.lower()
    output = []
    for needle in needles:
        index = lower.find(needle.lower())
        if index >= 0:
            output.append({"needle": needle, "snippet": text[max(0, index - 600): index + len(needle) + 1800]})
    return output


def json_or_preview(text: str) -> Any:
    try:
        value = json.loads(text)
        if isinstance(value, list):
            return {"shape": "list", "count": len(value), "sample": value[:20]}
        if isinstance(value, Mapping):
            return {"shape": "object", "keys": list(value)[:100], "sample": value}
        return value
    except json.JSONDecodeError:
        return {"text_preview": text[:5000]}


def main() -> int:
    skill_status, skill_type, skill_text = fetch(URLS["skill"], "text/markdown,text/plain,*/*")
    openapi_status, openapi_type, openapi_text = fetch(URLS["openapi"], "application/json")
    if openapi_status != 200:
        raise RuntimeError(f"Callboard OpenAPI HTTP {openapi_status}: {openapi_text[:1000]}")
    document = json.loads(openapi_text)
    paths = document.get("paths") if isinstance(document, Mapping) else {}
    selected: dict[str, Any] = {}
    for target in TARGETS:
        item = paths.get(target) if isinstance(paths, Mapping) else None
        if not isinstance(item, Mapping):
            selected[target] = {"missing": True}
            continue
        selected[target] = {
            method.upper(): compact_operation(document, operation)
            for method, operation in item.items()
            if method.lower() in {"get", "post", "patch", "put", "delete"} and isinstance(operation, Mapping)
        }

    public_reads: dict[str, Any] = {}
    for key in ("capabilities", "tags", "job_types"):
        status, content_type, text = fetch(URLS[key], "application/json")
        public_reads[key] = {
            "url": URLS[key],
            "status": status,
            "content_type": content_type,
            "result": json_or_preview(text),
        }

    report = {
        "generated_at": now_iso(),
        "writes_performed": [],
        "skill": {
            "url": URLS["skill"],
            "status": skill_status,
            "content_type": skill_type,
            "snippets": snippets(skill_text),
            "sha256_note": "Raw skill text intentionally not persisted; only bounded onboarding snippets are stored.",
        },
        "openapi": {
            "url": URLS["openapi"],
            "status": openapi_status,
            "content_type": openapi_type,
            "title": (document.get("info") or {}).get("title") if isinstance(document, Mapping) else None,
            "version": (document.get("info") or {}).get("version") if isinstance(document, Mapping) else None,
            "servers": document.get("servers") if isinstance(document, Mapping) else None,
            "selected_operations": selected,
        },
        "public_reads": public_reads,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "output": str(OUTPUT), "operations": len(selected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
