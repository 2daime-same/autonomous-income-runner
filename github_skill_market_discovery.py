#!/usr/bin/env python3
"""Discover paid-work APIs advertised through public agent skill files.

The script searches GitHub's public code index for skill documents describing paid
jobs, tasks, bounties, or escrow. It fetches only public documentation and public
GET inventory routes. It does not register, authenticate, sign, bid, claim, submit,
pay, create wallets, accept terms, or withdraw.
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

OUTPUT = Path(os.environ.get("SKILL_MARKET_OUTPUT", "market-output/github-skill-markets.json"))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TIMEOUT = 40
MAX_DOC_BYTES = 300_000
MAX_RESULTS_PER_QUERY = 50
MAX_SKILLS = 80
MAX_PROBES = 160

SEARCH_QUERIES = (
    '"get paid" filename:skill.md jobs',
    '"get paid" filename:SKILL.md bounties',
    '"job marketplace" filename:skill.md "AI agent"',
    '"job marketplace" filename:SKILL.md agent',
    '"api_base" filename:skill.md jobs',
    '"api_base" filename:SKILL.md bounties',
    '"browse open jobs" filename:skill.md',
    '"complete tasks" filename:skill.md paid',
    '"escrow" filename:skill.md jobs',
    '"escrow" filename:SKILL.md bounties',
    '"workers/register" filename:skill.md',
    '"agents/register" filename:skill.md jobs',
    '"jobs?status=open" filename:skill.md',
    '"bounties?status=open" filename:skill.md',
)

KNOWN_HOSTS = {
    "api.moltjobs.io",
    "molt-jobs.com",
    "moltbotmarket.com",
    "www.moltbotmarket.com",
    "moltcities.org",
    "api.worq.dev",
    "worq.dev",
    "api.getcallboard.com",
    "getcallboard.com",
    "api.agenthire.app",
    "agenthire.app",
    "www.agenthire.app",
    "agrenting.com",
    "agent-job.ai",
    "api.agent-job.ai",
    "clawlancer.ai",
    "clawhunt.store",
    "api.agentbounties.app",
    "superteam.fun",
    "www.task-bounty.com",
}

INVENTORY_MARKERS = ("job", "task", "bount", "gig", "opportun", "listing", "market", "call")
BLOCKED_PATH_MARKERS = (
    "register", "signup", "login", "claim", "apply", "bid", "submit", "approve", "accept",
    "start", "withdraw", "wallet", "payment", "purchase", "buy", "deposit", "fund", "sign",
)
DOC_PAID_MARKERS = ("get paid", "paid work", "reward", "bounty", "escrow", "earnings", "payment")
DOC_WORK_MARKERS = ("jobs", "tasks", "bounties", "opportunities", "marketplace", "work")
SUSPICIOUS_MARKERS = (
    "referral only", "guaranteed profit", "send funds", "seed phrase", "private key", "double your",
    "casino", "gambling", "betting", "adult content", "porn", "malware", "credential theft",
)
SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|authorization|bearer|access[_-]?token|refresh[_-]?token|secret|private[_-]?key|claim[_-]?code)")
ABS_URL_RE = re.compile(r"https?://[^\s<>'\"`\\)\]]+")
PATH_RE = re.compile(r"(?im)(?:GET|curl(?:\s+-[^\n]+)?)\s+[\"']?(/[^\s\"']+)")
API_BASE_RE = re.compile(r"(?im)(?:api_base|api\s*base|base\s*url)\s*[:=]\s*[`\"']?(https?://[^\s`\"']+)")
FRONTMATTER_API_RE = re.compile(r"(?im)^api_base\s*:\s*(https?://\S+)\s*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, nested in value.items():
            key = str(raw_key)
            result[key] = "[REDACTED]" if SECRET_KEY_RE.search(key) else sanitize(nested)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\b(?:sk|pk|api|key|token)_[A-Za-z0-9_-]{16,}\b", "[REDACTED]", value)
        value = re.sub(r"\b0x[a-fA-F0-9]{64}\b", "[REDACTED_HEX]", value)
        return value[:10000]
    return value


def redact_url(raw: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(raw)
        query = []
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            query.append((key, "[REDACTED]" if SECRET_KEY_RE.search(key) else value))
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))
    except Exception:
        return raw[:1500]


def request(url: str, *, github: bool = False) -> tuple[int, Any, Mapping[str, str], str]:
    headers = {
        "Accept": "application/vnd.github+json" if github else "application/json,text/markdown,text/plain,text/html;q=0.8,*/*;q=0.2",
        "User-Agent": "nexaworks-github-skill-market-discovery/1.0",
    }
    if github and GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read(MAX_DOC_BYTES + 1)[:MAX_DOC_BYTES]
            text = raw.decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            payload: Any = None
            if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
            return response.status, payload, dict(response.headers.items()), text
    except urllib.error.HTTPError as error:
        text = error.read(20_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        return error.code, payload, dict(error.headers.items()) if error.headers else {}, text
    except Exception as error:
        return 0, {"error": f"{type(error).__name__}: {error}"}, {}, ""


def github_search(query: str) -> list[Mapping[str, Any]]:
    url = "https://api.github.com/search/code?" + urllib.parse.urlencode({"q": query, "per_page": MAX_RESULTS_PER_QUERY})
    status, payload, headers, _ = request(url, github=True)
    if status == 403:
        reset = headers.get("x-ratelimit-reset")
        if reset and reset.isdigit():
            delay = max(1, min(35, int(reset) - int(time.time()) + 1))
            time.sleep(delay)
            status, payload, _, _ = request(url, github=True)
    if status != 200 or not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
        return []
    return [item for item in payload["items"] if isinstance(item, Mapping)]


def fetch_github_content(item: Mapping[str, Any]) -> tuple[str, str] | None:
    repository = item.get("repository")
    if not isinstance(repository, Mapping):
        return None
    full_name = repository.get("full_name")
    path = item.get("path")
    if not isinstance(full_name, str) or not isinstance(path, str):
        return None
    url = f"https://api.github.com/repos/{full_name}/contents/{urllib.parse.quote(path, safe='/')}"
    status, payload, _, _ = request(url, github=True)
    if status != 200 or not isinstance(payload, Mapping):
        return None
    download_url = payload.get("download_url")
    if not isinstance(download_url, str):
        return None
    status, _, _, text = request(download_url)
    if status != 200:
        return None
    return download_url, text


def doc_is_paid_market(text: str) -> tuple[bool, list[str]]:
    lower = text.lower()
    reasons: list[str] = []
    paid = [marker for marker in DOC_PAID_MARKERS if marker in lower]
    work = [marker for marker in DOC_WORK_MARKERS if marker in lower]
    if paid:
        reasons.append("paid markers: " + ", ".join(paid[:6]))
    if work:
        reasons.append("work markers: " + ", ".join(work[:6]))
    suspicious = [marker for marker in SUSPICIOUS_MARKERS if marker in lower]
    if suspicious:
        reasons.append("suspicious markers: " + ", ".join(suspicious))
    return bool(paid and work and not suspicious), reasons


def safe_inventory_url(raw: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(raw)
    except Exception:
        return False
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    lower = parsed.path.lower()
    if "{" in lower or "}" in lower:
        return False
    if any(marker in lower for marker in BLOCKED_PATH_MARKERS):
        return False
    return any(marker in lower for marker in INVENTORY_MARKERS)


def bases_from_doc(download_url: str, text: str) -> list[str]:
    bases: list[str] = []
    for pattern in (FRONTMATTER_API_RE, API_BASE_RE):
        for match in pattern.finditer(text):
            bases.append(match.group(1).rstrip("/"))
    for match in ABS_URL_RE.finditer(text):
        candidate = match.group(0).rstrip(".,;:")
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.path.rstrip("/").endswith(("/api", "/api/v1", "/v1")):
            bases.append(candidate.rstrip("/"))
    if not bases:
        parsed = urllib.parse.urlsplit(download_url)
        bases.append(f"{parsed.scheme}://{parsed.netloc}")
    return list(dict.fromkeys(bases))[:10]


def inventory_urls(download_url: str, text: str) -> list[str]:
    bases = bases_from_doc(download_url, text)
    urls: set[str] = set()
    for match in ABS_URL_RE.finditer(text):
        candidate = match.group(0).rstrip(".,;:")
        if safe_inventory_url(candidate):
            urls.add(candidate)
    for match in PATH_RE.finditer(text):
        path = match.group(1)
        if safe_inventory_url("https://placeholder.invalid" + path):
            for base in bases:
                urls.add(urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/")))
    return sorted(urls)[:30]


def unwrap(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "items", "jobs", "tasks", "bounties", "gigs", "opportunities", "listings", "calls", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
            if isinstance(candidate, Mapping):
                nested = unwrap(candidate)
                if nested:
                    return nested
    return []


def compact_item(item: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "title", "name", "description", "summary", "status", "state", "reward", "reward_amount",
        "rewardAmount", "budget", "budget_usdc", "budgetUsdc", "amount", "bounty", "bounty_cents",
        "currency", "deadline", "deadlineAt", "deadline_at", "expiresAt", "expires_at", "paymentStatus",
        "payment_status", "escrowStatus", "escrow_status", "acceptanceCriteria", "acceptance_criteria", "url",
        "publicUrl", "public_url",
    )
    return sanitize({key: item.get(key) for key in keys if item.get(key) is not None})


def main() -> int:
    found: dict[str, dict[str, Any]] = {}
    query_results: dict[str, int] = {}
    for query in SEARCH_QUERIES:
        items = github_search(query)
        query_results[query] = len(items)
        for item in items:
            repository = item.get("repository")
            if not isinstance(repository, Mapping):
                continue
            full_name = repository.get("full_name")
            path = item.get("path")
            if not isinstance(full_name, str) or not isinstance(path, str):
                continue
            marker = full_name + ":" + path
            found.setdefault(marker, {"repository": full_name, "path": path, "html_url": item.get("html_url")})
        if len(found) >= MAX_SKILLS:
            break
        time.sleep(1)

    skills: list[dict[str, Any]] = []
    probes_used = 0
    for marker, metadata in list(found.items())[:MAX_SKILLS]:
        content = fetch_github_content({
            "repository": {"full_name": metadata["repository"]},
            "path": metadata["path"],
        })
        if not content:
            continue
        download_url, text = content
        qualifies, reasons = doc_is_paid_market(text)
        urls = inventory_urls(download_url, text) if qualifies else []
        endpoint_results: list[dict[str, Any]] = []
        for url in urls:
            if probes_used >= MAX_PROBES:
                break
            probes_used += 1
            host = urllib.parse.urlsplit(url).netloc.lower()
            status, payload, _, response_text = request(url)
            records = unwrap(payload)
            endpoint_results.append({
                "url": redact_url(url),
                "known_host": host in KNOWN_HOSTS,
                "status": status,
                "record_count": len(records),
                "items": [compact_item(item) for item in records[:50]],
                "error_preview": sanitize(response_text[:1500]) if status >= 400 else None,
            })
            time.sleep(0.15)
        skills.append({
            **metadata,
            "download_url": redact_url(download_url),
            "qualifies_as_paid_market": qualifies,
            "qualification_reasons": reasons,
            "api_bases": [redact_url(value) for value in bases_from_doc(download_url, text)],
            "inventory_urls": [redact_url(value) for value in urls],
            "public_inventory_records": sum(item["record_count"] for item in endpoint_results if item["status"] == 200),
            "endpoint_results": endpoint_results,
            "document_excerpt": sanitize(text[:5000]),
        })

    skills.sort(
        key=lambda item: (
            int(item.get("public_inventory_records") or 0),
            len(item.get("inventory_urls") or []),
            bool(item.get("qualifies_as_paid_market")),
        ),
        reverse=True,
    )
    report = {
        "generated_at": now_iso(),
        "safety": "Public GitHub/code/docs and public GET inventory only; no registration or mutation",
        "queries": query_results,
        "unique_skill_files": len(found),
        "skills_inspected": len(skills),
        "public_probe_count": probes_used,
        "candidates_with_public_inventory": sum(1 for item in skills if item["public_inventory_records"] > 0),
        "skills": skills,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({
        "ok": True,
        "skills": len(skills),
        "public_inventory_candidates": report["candidates_with_public_inventory"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
