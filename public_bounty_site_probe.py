#!/usr/bin/env python3
"""Bounded, read-only discovery for public bounty marketplace APIs.

The probe fetches only public pages, JavaScript assets, and a fixed allowlist of
GET endpoints. It never authenticates, creates accounts, claims work, pays,
signs, or mutates external data. Output is compact so an agent can inspect it
without ingesting megabytes of framework bundles.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path(os.environ.get("PUBLIC_BOUNTY_SITE_OUTPUT", "market-output/public-bounty-sites.json"))
TIMEOUT = 45
MAX_PAGE_BYTES = 3_000_000
MAX_ASSET_BYTES = 2_000_000
MAX_ASSETS_PER_SITE = 50
USER_AGENT = "autonomous-income-runner-public-bounty-discovery/1.1"

SITES = {
    "gitwork": {
        "origin": "https://gitwork.io",
        "start_paths": ["/", "/about"],
        "api_origins": ["https://gitwork.io", "https://api.gitwork.io"],
        "api_paths": [
            "/api/bounties",
            "/api/bounties?status=open",
            "/api/issues",
            "/api/stats",
            "/api/v1/bounties",
            "/bounties.json",
        ],
    },
    "bountyhub": {
        "origin": "https://www.bountyhub.dev",
        "start_paths": ["/en", "/en/bounties", "/en/explore"],
        "api_origins": [
            "https://www.bountyhub.dev",
            "https://api.bountyhub.dev/api",
        ],
        "api_paths": [
            "",
            "/bounties",
            "/bounties/",
            "/bounties?status=open",
            "/bounties/?status=open",
            "/bounties?ordering=-amount",
            "/bounties/?ordering=-amount",
            "/bounties?limit=100",
            "/bounties/?limit=100",
            "/featured-bounties",
            "/featured-bounties/",
            "/bounties/featured",
            "/bounties/featured/",
            "/issues",
            "/issues/",
            "/repositories",
            "/repositories/",
            "/projects",
            "/projects/",
            "/api/bounties",
            "/api/bounties?status=open",
        ],
    },
    "codebounty": {
        "origin": "https://www.codebounty.org",
        "start_paths": ["/", "/bounties"],
        "api_origins": [
            "https://www.codebounty.org",
            "https://api.codebounty.org",
        ],
        "api_paths": [
            "/api/bounties",
            "/api/bounties?status=open",
            "/api/issues",
            "/api/stats",
            "/api/v1/bounties",
            "/bounties.json",
        ],
    },
}

ALLOWED_HOSTS = {
    "gitwork.io",
    "api.gitwork.io",
    "www.bountyhub.dev",
    "api.bountyhub.dev",
    "www.codebounty.org",
    "api.codebounty.org",
}

NEEDLES = [
    "gitwork:usdc:",
    "gitwork:sol:",
    "github.com/",
    "issue_url",
    "issueUrl",
    "issue_number",
    "issueNumber",
    "repository_url",
    "repositoryUrl",
    "bounty",
    "escrow",
    "funded",
    "reward",
    "amount_cents",
    "amountCents",
    "/api/",
    "api.bountyhub.dev",
    "supabase",
    "graphql",
    "convex",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request(url: str, max_bytes: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/html,application/javascript,text/javascript,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read(max_bytes)
            text = raw.decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            try:
                parsed: Any = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return {
                "ok": True,
                "status": response.status,
                "url": response.geturl(),
                "content_type": content_type,
                "bytes_read": len(raw),
                "json": parsed,
                "text": None if parsed is not None else text,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(min(max_bytes, 500_000))
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        return {
            "ok": False,
            "status": exc.code,
            "url": url,
            "content_type": exc.headers.get("content-type", ""),
            "bytes_read": len(raw),
            "json": parsed,
            "text": None if parsed is not None else text,
        }
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def absolute(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value))


def host_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.netloc in ALLOWED_HOSTS


def extract_script_urls(text: str, page_url: str, origin: str) -> list[str]:
    origin_host = urllib.parse.urlparse(origin).netloc
    urls = {
        absolute(page_url, match.group(1))
        for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, re.I)
    }
    return sorted(
        url
        for url in urls
        if urllib.parse.urlparse(url).scheme == "https"
        and urllib.parse.urlparse(url).netloc == origin_host
    )[:MAX_ASSETS_PER_SITE]


def extract_candidate_urls(text: str, origin: str) -> list[str]:
    values: set[str] = set()
    patterns = [
        r"https?://[^\s\"'<>\\]+",
        r"[\"'](/api/[^\"']+)[\"']",
        r"[\"']([^\"']*(?:bount|issue|market|escrow|reward)[^\"']*)[\"']",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = match.group(1) if match.lastindex else match.group(0)
            value = html.unescape(value).rstrip(")]},;`\"'")
            if not value or len(value) > 600:
                continue
            if value.startswith("/"):
                value = absolute(origin + "/", value)
            values.add(value)
    return sorted(values)


def github_urls(text: str) -> list[str]:
    return sorted(
        {
            html.unescape(match.group(0)).rstrip(")]},;`\"'")
            for match in re.finditer(
                r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[0-9]+",
                text,
            )
        }
    )


def snippets(text: str, radius: int = 350, per_needle: int = 3) -> list[dict[str, str]]:
    lower = text.lower()
    found: list[dict[str, str]] = []
    for needle in NEEDLES:
        target = needle.lower()
        start = 0
        matches = 0
        while matches < per_needle:
            index = lower.find(target, start)
            if index < 0:
                break
            found.append(
                {
                    "needle": needle,
                    "snippet": text[max(0, index - radius) : index + len(needle) + radius],
                }
            )
            matches += 1
            start = index + len(target)
    return found[:80]


def compact_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        if isinstance(value, (dict, list)):
            return f"<{type(value).__name__}>"
        return value
    if isinstance(value, Mapping):
        keys = list(value)[:80]
        return {str(key): compact_json(value[key], depth=depth + 1) for key in keys}
    if isinstance(value, list):
        return [compact_json(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:2000]
    return value


def json_summary(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"shape": type(value).__name__}
    if isinstance(value, list):
        summary["count"] = len(value)
        summary["sample"] = compact_json(value[:10])
    elif isinstance(value, Mapping):
        summary["keys"] = list(value)[:100]
        for key in ("count", "total", "next", "next_cursor", "results", "items", "data", "bounties"):
            item = value.get(key)
            if item is not None:
                if isinstance(item, list):
                    summary[f"{key}_count"] = len(item)
                    summary[f"{key}_sample"] = compact_json(item[:10])
                else:
                    summary[key] = compact_json(item)
        if not any(key.endswith("_sample") for key in summary):
            summary["sample"] = compact_json(value)
    else:
        summary["value"] = compact_json(value)
    return summary


def compact_response(response: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: response.get(key)
        for key in ("ok", "status", "url", "content_type", "bytes_read", "error")
        if response.get(key) is not None
    }
    if response.get("json") is not None:
        result["json_summary"] = json_summary(response["json"])
    elif isinstance(response.get("text"), str):
        text = response["text"]
        result["text_preview"] = text[:2500]
        result["github_issue_urls"] = github_urls(text)[:100]
        result["interesting_snippets"] = snippets(text)[:15]
    return result


def successful_json_endpoints(endpoint_results: Mapping[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for url, result in endpoint_results.items():
        if not isinstance(result, Mapping) or result.get("json_summary") is None:
            continue
        values.append(
            {
                "url": url,
                "status": result.get("status"),
                "ok": result.get("ok"),
                "json_summary": result.get("json_summary"),
            }
        )
    return values


def probe_site(name: str, config: Mapping[str, Any]) -> dict[str, Any]:
    origin = str(config["origin"]).rstrip("/")
    start_paths = config.get("start_paths") if isinstance(config.get("start_paths"), list) else ["/"]
    pages: list[dict[str, Any]] = []
    scripts: dict[str, dict[str, Any]] = {}
    combined = ""

    for path_value in start_paths:
        page_url = absolute(origin + "/", str(path_value))
        response = request(page_url, MAX_PAGE_BYTES)
        text = response.get("text") if isinstance(response.get("text"), str) else ""
        combined += "\n" + text
        pages.append(compact_response(response))
        for script_url in extract_script_urls(text, page_url, origin):
            if script_url in scripts or len(scripts) >= MAX_ASSETS_PER_SITE:
                continue
            script = request(script_url, MAX_ASSET_BYTES)
            script_text = script.get("text") if isinstance(script.get("text"), str) else ""
            combined += "\n" + script_text
            interesting = snippets(script_text)[:20]
            issue_urls = github_urls(script_text)[:100]
            candidate_api_urls = [
                value
                for value in extract_candidate_urls(script_text, origin)
                if host_allowed(value) and "/api" in urllib.parse.urlparse(value).path
            ][:100]
            if interesting or issue_urls or candidate_api_urls:
                scripts[script_url] = {
                    "ok": script.get("ok"),
                    "status": script.get("status"),
                    "bytes_read": script.get("bytes_read"),
                    "github_issue_urls": issue_urls,
                    "candidate_api_urls": candidate_api_urls,
                    "interesting_snippets": interesting,
                }

    discovered_urls = extract_candidate_urls(combined, origin)
    endpoint_urls: set[str] = set()
    api_origins = config.get("api_origins") if isinstance(config.get("api_origins"), list) else [origin]
    api_paths = config.get("api_paths") if isinstance(config.get("api_paths"), list) else []
    for api_origin in api_origins:
        api_origin = str(api_origin).rstrip("/")
        if not host_allowed(api_origin):
            continue
        for path_value in api_paths:
            endpoint_urls.add(api_origin + str(path_value))
    for url in discovered_urls:
        if host_allowed(url) and "/api" in urllib.parse.urlparse(url).path:
            endpoint_urls.add(url)

    endpoint_results = {
        url: compact_response(request(url, 2_000_000))
        for url in sorted(endpoint_urls)[:120]
    }
    issue_urls = github_urls(combined)[:300]
    return {
        "name": name,
        "origin": origin,
        "pages": pages,
        "inspected_script_count": len(scripts),
        "scripts": scripts,
        "github_issue_urls": issue_urls,
        "candidate_api_urls": [
            url
            for url in discovered_urls
            if host_allowed(url) and "/api" in urllib.parse.urlparse(url).path
        ][:300],
        "successful_json_endpoints": successful_json_endpoints(endpoint_results),
        "endpoint_results": endpoint_results,
        "summary": {
            "github_issue_url_count": len(issue_urls),
            "successful_json_endpoint_count": len(successful_json_endpoints(endpoint_results)),
            "inspected_script_count": len(scripts),
        },
    }


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def main() -> int:
    report = {
        "generated_at": now_iso(),
        "safety": "public GET-only allowlist; no auth, claim, payment, signing, or mutation",
        "sites": {},
    }
    for name, config in SITES.items():
        try:
            report["sites"][name] = {"ok": True, "result": probe_site(name, config)}
        except Exception as exc:
            report["sites"][name] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    atomic_write(OUTPUT, report)
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(OUTPUT),
                "sites": {
                    key: {
                        "ok": value.get("ok"),
                        "summary": (value.get("result") or {}).get("summary"),
                    }
                    for key, value in report["sites"].items()
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
