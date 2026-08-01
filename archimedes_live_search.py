#!/usr/bin/env python3
"""Audit the current public Archimedes bounty inventory through its official MCP.

The scanner performs a bounded, read-only, one-shot lookup. It does not register an
account, accept terms, connect Stripe, submit work, message users, or create a
transaction. Public results are committed as evidence for execution decisions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ENDPOINT = "https://archimedes.market/api/mcp"
OUTPUT = Path(os.environ.get("ARCHIMEDES_OUTPUT", "market-output/archimedes-live.json"))
USER_AGENT = "autonomous-income-runner-archimedes-audit/2.0"
SEARCHES: tuple[tuple[str, str | None], ...] = (
    ("all_open", None),
    ("MSN-00013", "MSN-00013"),
    ("MSN-00014", "MSN-00014"),
    ("MSN-00015", "MSN-00015"),
    ("github_pr_mcp", "GitHub pull request MCP"),
    ("unit_conversion", "unit conversion"),
    ("mcp", "MCP"),
    ("api", "API"),
)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
MISSION_RE = re.compile(r"^MSN-[0-9]{5}$", re.I)
SECRET_RE = re.compile(
    r"(?i)(authorization\s*[:=]|bearer\s+[A-Za-z0-9._~+/=-]{16,}|"
    r"\b(?:sk|pk|ghp|gho|ghs|github_pat)_[A-Za-z0-9_=-]{16,}\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


class ScannerError(RuntimeError):
    pass


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def parse_response(raw: str, content_type: str) -> Any:
    text = raw.strip()
    if not text:
        raise ScannerError("Archimedes returned an empty response")
    if "text/event-stream" in content_type.lower() or text.startswith("data:"):
        events: list[Any] = []
        chunks: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                chunks.append(line[5:].strip())
            elif not line.strip() and chunks:
                candidate = "\n".join(chunks)
                chunks.clear()
                if candidate and candidate != "[DONE]":
                    try:
                        events.append(json.loads(candidate))
                    except json.JSONDecodeError:
                        events.append({"unparsed_data": candidate[:20_000]})
        if chunks:
            candidate = "\n".join(chunks)
            if candidate and candidate != "[DONE]":
                try:
                    events.append(json.loads(candidate))
                except json.JSONDecodeError:
                    events.append({"unparsed_data": candidate[:20_000]})
        if not events:
            raise ScannerError("Archimedes returned SSE without a JSON event")
        return events[-1] if len(events) == 1 else {"events": events}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScannerError(f"Archimedes returned non-JSON content: {text[:1000]}") from exc


def post_json(payload: Mapping[str, Any], attempts: int = 2) -> Any:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
        "User-Agent": USER_AGENT,
    }
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(ENDPOINT, data=encoded, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return parse_response(raw, response.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            last_error = ScannerError(f"HTTP {exc.code}: {raw[:2000]}")
            if exc.code < 500 or attempt >= attempts:
                raise last_error from exc
        except (urllib.error.URLError, TimeoutError, ScannerError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise ScannerError(f"Request failed: {exc}") from exc
        time.sleep(attempt * 2)
    raise ScannerError(f"Request failed: {last_error}")


def rpc(method: str, params: Mapping[str, Any] | None, request_id: int) -> Any:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = dict(params)
    response = post_json(payload)
    if isinstance(response, Mapping) and response.get("error") is not None:
        raise ScannerError(f"JSON-RPC error for {method}: {response['error']}")
    return response


def result_value(response: Any) -> Any:
    if isinstance(response, Mapping) and "result" in response:
        return response["result"]
    if isinstance(response, Mapping) and isinstance(response.get("events"), list):
        for event in reversed(response["events"]):
            if isinstance(event, Mapping) and "result" in event:
                return event["result"]
    return response


def decode_embedded_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): decode_embedded_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_embedded_json(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")) and len(stripped) <= 1_000_000:
            try:
                return decode_embedded_json(json.loads(stripped))
            except json.JSONDecodeError:
                return value
    return value


def tool_list(response: Any) -> list[dict[str, Any]]:
    value = result_value(response)
    if isinstance(value, Mapping) and isinstance(value.get("tools"), list):
        return [dict(item) for item in value["tools"] if isinstance(item, Mapping)]
    return []


def tool_by_name(tools: Iterable[Mapping[str, Any]], name: str) -> dict[str, Any] | None:
    for tool in tools:
        if str(tool.get("name") or "") == name:
            return dict(tool)
    return None


def schema_properties(tool: Mapping[str, Any] | None) -> dict[str, Any]:
    if not tool:
        return {}
    schema = tool.get("inputSchema") or tool.get("input_schema")
    if isinstance(schema, Mapping) and isinstance(schema.get("properties"), Mapping):
        return {str(key): value for key, value in schema["properties"].items()}
    return {}


def enum_values(schema: Any) -> list[str]:
    if not isinstance(schema, Mapping):
        return []
    values = schema.get("enum")
    return [str(value) for value in values] if isinstance(values, list) else []


def search_arguments(tool: Mapping[str, Any] | None, query: str | None) -> dict[str, Any]:
    properties = schema_properties(tool)
    arguments: dict[str, Any] = {}
    if query and "query" in properties:
        arguments["query"] = query
    if "limit" in properties:
        arguments["limit"] = 50
    if "offset" in properties:
        arguments["offset"] = 0
    if "page" in properties:
        arguments["page"] = 1
    if "page_size" in properties:
        arguments["page_size"] = 50
    for field in ("funding_status", "fundingStatus", "status"):
        if field not in properties:
            continue
        values = enum_values(properties[field])
        for preferred in ("open", "funded", "all"):
            if preferred in values:
                arguments[field] = preferred
                break
    return arguments


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def is_bounty_record(item: Mapping[str, Any]) -> bool:
    identifier = item.get("id")
    title = item.get("title")
    price = item.get("price_cents") if "price_cents" in item else item.get("payout_cents")
    url = item.get("url") or item.get("public_url")
    return (
        isinstance(identifier, str)
        and UUID_RE.fullmatch(identifier) is not None
        and isinstance(title, str)
        and bool(title.strip())
        and isinstance(price, (int, float))
        and isinstance(url, str)
        and "/bounties/" in url
    )


def candidate_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in walk(value):
        if not isinstance(item, Mapping) or not is_bounty_record(item):
            continue
        identifier = str(item["id"]).lower()
        if identifier in seen:
            continue
        seen.add(identifier)
        records.append(dict(item))
    return records


def record_identifiers(records: Iterable[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    uuids: list[str] = []
    displays: list[str] = []
    seen_uuids: set[str] = set()
    seen_displays: set[str] = set()
    for record in records:
        identifier = record.get("id")
        if isinstance(identifier, str) and UUID_RE.fullmatch(identifier):
            normalized = identifier.lower()
            if normalized not in seen_uuids:
                seen_uuids.add(normalized)
                uuids.append(identifier)
        display = record.get("display_id")
        if isinstance(display, str) and MISSION_RE.fullmatch(display):
            normalized_display = display.upper()
            if normalized_display not in seen_displays:
                seen_displays.add(normalized_display)
                displays.append(normalized_display)
    return uuids, displays


def details_arguments(tool: Mapping[str, Any] | None, identifier: str) -> dict[str, Any] | None:
    properties = schema_properties(tool)
    for field in ("bounty_id", "bountyId", "id", "uuid", "mission_id", "missionId"):
        if field in properties:
            return {field: identifier}
    return None


def assert_public_output(value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if SECRET_RE.search(text):
        raise ScannerError("Credential-like material appeared in public Archimedes output")


def main() -> int:
    request_id = 1
    listed = rpc("tools/list", {}, request_id)
    request_id += 1
    tools = tool_list(listed)
    search_tool = tool_by_name(tools, "search_bounties")
    details_tool = tool_by_name(tools, "get_bounty_details")
    stats_tool = tool_by_name(tools, "get_platform_stats")
    if search_tool is None:
        raise ScannerError("Official MCP endpoint did not advertise search_bounties")

    searches: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    for label, query in SEARCHES:
        arguments = search_arguments(search_tool, query)
        response = rpc(
            "tools/call",
            {"name": "search_bounties", "arguments": arguments},
            request_id,
        )
        request_id += 1
        decoded = decode_embedded_json(result_value(response))
        records = candidate_records(decoded)
        record_uuids, record_displays = record_identifiers(records)
        searches.append(
            {
                "label": label,
                "query": query,
                "arguments": arguments,
                "candidate_record_count": len(records),
                "bounty_uuids": record_uuids,
                "display_ids": record_displays,
                "result": decoded,
            }
        )
        all_records.extend(records)
        time.sleep(0.6)

    records_by_id: dict[str, dict[str, Any]] = {}
    for record in all_records:
        records_by_id[str(record["id"]).lower()] = record
    deduped_records = sorted(
        records_by_id.values(),
        key=lambda item: (-int(item.get("price_cents") or 0), str(item.get("display_id") or "")),
    )
    unique_ids, display_ids = record_identifiers(deduped_records)

    details: list[dict[str, Any]] = []
    if details_tool is not None:
        for identifier in unique_ids[:50]:
            arguments = details_arguments(details_tool, identifier)
            if arguments is None:
                break
            try:
                response = rpc(
                    "tools/call",
                    {"name": "get_bounty_details", "arguments": arguments},
                    request_id,
                )
                request_id += 1
                details.append(
                    {
                        "identifier": identifier,
                        "arguments": arguments,
                        "result": decode_embedded_json(result_value(response)),
                    }
                )
            except ScannerError as exc:
                details.append({"identifier": identifier, "arguments": arguments, "error": str(exc)})
            time.sleep(0.6)

    stats: Any = None
    if stats_tool is not None:
        try:
            response = rpc("tools/call", {"name": "get_platform_stats", "arguments": {}}, request_id)
            stats = decode_embedded_json(result_value(response))
        except ScannerError as exc:
            stats = {"error": str(exc)}

    output = {
        "schema_version": "archimedes-live-audit-v2",
        "generated_at": iso_now(),
        "source": ENDPOINT,
        "mode": "public_read_only_one_shot",
        "commercial_status": {
            "verified_income_usd": 0,
            "verified_receivable_usd": 0,
            "expenses_usd": 0,
            "submission_performed": False,
            "account_action_performed": False,
        },
        "advertised_tools": tools,
        "platform_stats": stats,
        "search_count": len(searches),
        "searches": searches,
        "open_bounty_count": len(deduped_records),
        "open_bounties": deduped_records,
        "bounty_uuids": unique_ids,
        "display_ids": display_ids,
        "details": details,
    }
    assert_public_output(output)
    atomic_json(OUTPUT, output)
    print(json.dumps({
        "ok": True,
        "output": str(OUTPUT),
        "open_bounties": len(deduped_records),
        "details": len(details),
        "display_ids": display_ids,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
