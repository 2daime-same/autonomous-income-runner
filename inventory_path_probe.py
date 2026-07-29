#!/usr/bin/env python3
"""Extract public GET inventory routes from market specs and probe them.

The program is deliberately read-only. It never registers, authenticates, signs,
bids, claims, submits, pays, or withdraws. It exists to distinguish a real live
work queue from marketing pages before any account is created.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path(os.environ.get("INVENTORY_PATH_OUTPUT", "market-output/inventory-paths.json"))
TIMEOUT = 40
MAX_BYTES = 1_000_000

MARKETS: dict[str, dict[str, list[str]]] = {
    "worq": {
        "specs": ["https://api.worq.dev/openapi.json", "https://worq.dev/skill.md"],
        "bases": ["https://api.worq.dev"],
    },
    "callboard": {
        "specs": ["https://api.getcallboard.com/openapi.json", "https://getcallboard.com/skill.md"],
        "bases": ["https://api.getcallboard.com"],
    },
    "agenthire": {
        "specs": ["https://api.agenthire.app/openapi.json", "https://www.agenthire.app/skill.md"],
        "bases": ["https://api.agenthire.app"],
    },
    "agrenting": {
        "specs": ["https://agrenting.com/skill.md", "https://agrenting.com/openapi.json"],
        "bases": ["https://agrenting.com", "https://api.agrenting.com"],
    },
    "agentjob": {
        "specs": ["https://agent-job.ai/skill.md", "https://agent-job.ai/openapi.json"],
        "bases": ["https://agent-job.ai", "https://api.agent-job.ai"],
    },
    "clawlancer": {
        "specs": ["https://clawlancer.ai/api/info", "https://clawlancer.ai/docs", "https://clawlancer.ai/openapi.json"],
        "bases": ["https://clawlancer.ai", "https://api.clawlancer.ai"],
    },
}

INVENTORY_MARKERS = ("job", "task", "bount", "gig", "opportun", "listing", "market")
UNSAFE_MARKERS = ("register", "signup", "claim", "apply", "bid", "submit", "approve", "withdraw", "wallet", "payment", "purchase", "buy")
ABS_URL = re.compile(r"https?://[^\s<>'\"`\\)\]]+")
METHOD_PATH = re.compile(r"(?im)^\s*(?:GET|curl(?:\s+-[^\n]+)?)\s+[\"']?(/[^\s\"']+)")
BASE_LINE = re.compile(r"(?im)(?:api_base|base\s+url)\s*[:=]\s*[`\"']?(https?://[^\s`\"']+)")
SECRET_KEY = re.compile(r"(?i)(api[_-]?key|authorization|bearer|token|secret|private[_-]?key|claim[_-]?code)")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        query = []
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            query.append((key, "[REDACTED]" if SECRET_KEY.search(key) else value))
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))
    except Exception:
        return url[:1000]


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): ("[REDACTED]" if SECRET_KEY.search(str(k)) else sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\b(?:sk|pk|api|key|token)_[A-Za-z0-9_-]{16,}\b", "[REDACTED]", value)
        value = re.sub(r"\b0x[a-fA-F0-9]{64}\b", "[REDACTED_HEX]", value)
        return value[:5000]
    return value


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json,text/markdown,text/plain,text/html;q=0.8,*/*;q=0.2", "User-Agent": "nexaworks-inventory-path-probe/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)[:MAX_BYTES]
            text = raw.decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            payload: Any = None
            if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
            return {"ok": True, "status": response.status, "url": redact_url(response.geturl()), "content_type": content_type, "text": text, "json": payload}
    except urllib.error.HTTPError as exc:
        body = exc.read(8000).decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "url": redact_url(url), "error_preview": sanitize(body[:2000])}
    except Exception as exc:
        return {"ok": False, "url": redact_url(url), "error": f"{type(exc).__name__}: {exc}"}


def inventory_path(path: str) -> bool:
    lower = urllib.parse.urlsplit(path).path.lower()
    if any(marker in lower for marker in UNSAFE_MARKERS):
        return False
    return any(marker in lower for marker in INVENTORY_MARKERS)


def resolve_base(source_url: str, server_url: str) -> str:
    if server_url.startswith("http://") or server_url.startswith("https://"):
        return server_url.rstrip("/")
    source = urllib.parse.urlsplit(source_url)
    return urllib.parse.urljoin(f"{source.scheme}://{source.netloc}/", server_url).rstrip("/")


def spec_routes(source_url: str, response: Mapping[str, Any], fallback_bases: list[str]) -> tuple[list[dict[str, Any]], set[str]]:
    routes: list[dict[str, Any]] = []
    urls: set[str] = set()
    payload = response.get("json")
    text = str(response.get("text") or "")

    if isinstance(payload, Mapping) and isinstance(payload.get("paths"), Mapping):
        server_bases: list[str] = []
        if isinstance(payload.get("servers"), list):
            for server in payload["servers"]:
                if isinstance(server, Mapping) and isinstance(server.get("url"), str):
                    server_bases.append(resolve_base(source_url, server["url"]))
        if not server_bases:
            server_bases = fallback_bases
        for path, methods in payload["paths"].items():
            if not isinstance(path, str) or not isinstance(methods, Mapping) or "get" not in methods:
                continue
            if "{" in path or not inventory_path(path):
                continue
            operation = methods.get("get") if isinstance(methods.get("get"), Mapping) else {}
            routes.append({
                "path": path,
                "summary": operation.get("summary"),
                "operation_id": operation.get("operationId"),
                "security": sanitize(operation.get("security")),
                "parameters": sanitize(operation.get("parameters")),
            })
            for base in server_bases:
                urls.add(urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/")))

    bases = list(fallback_bases)
    for match in BASE_LINE.finditer(text):
        bases.append(match.group(1).rstrip("/"))
    for match in ABS_URL.finditer(text):
        candidate = match.group(0).rstrip(".,;:")
        if inventory_path(candidate):
            urls.add(candidate)
    for match in METHOD_PATH.finditer(text):
        path = match.group(1)
        if "{" not in path and inventory_path(path):
            for base in bases:
                urls.add(urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/")))
    return routes, urls


def unwrap_items(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "items", "jobs", "tasks", "bounties", "gigs", "opportunities", "listings", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
            if isinstance(candidate, Mapping):
                nested = unwrap_items(candidate)
                if nested:
                    return nested
    return []


def pick(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item.get(key)
    return None


def amount(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value.replace(",", ""))
        return float(match.group(1)) if match else None
    if isinstance(value, Mapping):
        for key in ("amountUsd", "amount_usd", "usd", "usdc", "amount", "value", "budget", "reward", "cents"):
            result = amount(value.get(key))
            if result is not None:
                return result / 100 if key == "cents" else result
    return None


def compact(item: Mapping[str, Any]) -> dict[str, Any]:
    reward = pick(item, "reward", "budget", "budgetUsdc", "budget_usdc", "amount", "bounty", "bounty_cents", "compensation", "pay")
    return {
        "id": pick(item, "id", "jobId", "job_id", "taskId", "task_id", "slug"),
        "title": str(pick(item, "title", "name", "jobTitle", "task_title") or "")[:500],
        "description": str(pick(item, "description", "summary", "details", "goal", "prompt") or "")[:2500],
        "status": pick(item, "status", "state", "availability"),
        "reward": sanitize(reward),
        "amount_hint": amount(reward),
        "currency": pick(item, "currency", "rewardCurrency", "token"),
        "deadline": pick(item, "deadline", "deadlineAt", "deadline_at", "expiresAt", "expires_at"),
        "payment_status": pick(item, "paymentStatus", "payment_status", "escrowStatus", "escrow_status"),
        "acceptance_criteria": sanitize(pick(item, "acceptanceCriteria", "acceptance_criteria", "criteria", "deliverables")),
        "url": redact_url(str(pick(item, "url", "publicUrl", "public_url", "jobUrl", "job_url") or "")),
    }


def main() -> int:
    report: dict[str, Any] = {"generated_at": now_iso(), "safety": "GET-only", "markets": {}}
    for market, config in MARKETS.items():
        specs: list[dict[str, Any]] = []
        candidate_urls: set[str] = set()
        route_summaries: list[dict[str, Any]] = []
        for spec_url in config["specs"]:
            response = fetch(spec_url)
            routes, urls = spec_routes(spec_url, response, config["bases"])
            route_summaries.extend(routes)
            candidate_urls.update(urls)
            specs.append({
                "url": redact_url(spec_url),
                "ok": response.get("ok"),
                "status": response.get("status"),
                "content_type": response.get("content_type"),
                "routes_found": len(routes),
                "error": response.get("error") or response.get("error_preview"),
            })

        probes: list[dict[str, Any]] = []
        total_items = 0
        for url in sorted(candidate_urls)[:80]:
            response = fetch(url)
            items = unwrap_items(response.get("json"))
            total_items += len(items)
            probes.append({
                "url": redact_url(url),
                "ok": response.get("ok"),
                "status": response.get("status"),
                "content_type": response.get("content_type"),
                "item_count": len(items),
                "items": [compact(item) for item in items[:100]],
                "error": response.get("error") or response.get("error_preview"),
            })
            time.sleep(0.1)

        report["markets"][market] = {
            "specs": specs,
            "inventory_routes": route_summaries[:200],
            "candidate_urls": sorted(redact_url(url) for url in candidate_urls),
            "probe_count": len(probes),
            "inventory_item_count": total_items,
            "probes": probes,
        }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "markets": len(MARKETS)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
