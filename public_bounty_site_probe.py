#!/usr/bin/env python3
"""Bounded, read-only discovery for public bounty marketplace APIs.

This probe fetches only public pages and JavaScript assets from a fixed allowlist
of bounty marketplaces. It extracts public API paths, GitHub issue URLs, labels,
and bounty-related data snippets, then tries a small fixed set of GET endpoints.
It never authenticates, creates accounts, claims work, pays, signs, or mutates.
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
MAX_ASSETS_PER_SITE = 40
USER_AGENT = "autonomous-income-runner-public-bounty-discovery/1.0"

SITES = {
    "gitwork": {
        "origin": "https://gitwork.io",
        "start_paths": ["/", "/about"],
    },
    "bountyhub": {
        "origin": "https://www.bountyhub.dev",
        "start_paths": ["/en", "/en/explore"],
    },
    "codebounty": {
        "origin": "https://www.codebounty.org",
        "start_paths": ["/"],
    },
}

COMMON_ENDPOINTS = [
    "/api/bounties",
    "/api/bounties?status=open",
    "/api/bounty",
    "/api/issues",
    "/api/issues?status=open",
    "/api/marketplace",
    "/api/marketplace/bounties",
    "/api/open-bounties",
    "/api/public/bounties",
    "/api/search/bounties",
    "/api/stats",
    "/api/v1/bounties",
    "/api/v1/bounties?status=open",
    "/bounties.json",
]

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
    "supabase",
    "graphql",
    "convex",
]


class ProbeError(RuntimeError):
    pass


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


def same_origin(url: str, origin: str) -> bool:
    parsed_url = urllib.parse.urlparse(url)
    parsed_origin = urllib.parse.urlparse(origin)
    return parsed_url.scheme in {"http", "https"} and parsed_url.netloc == parsed_origin.netloc


def extract_script_urls(text: str, page_url: str, origin: str) -> list[str]:
    urls = {
        absolute(page_url, match.group(1))
        for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, re.I)
    }
    return sorted(url for url in urls if same_origin(url, origin))[:MAX_ASSETS_PER_SITE]


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
            value = html.unescape(value).rstrip(")]},;`")
            if not value or len(value) > 600:
                continue
            if value.startswith("/"):
                value = absolute(origin + "/", value)
            values.add(value)
    return sorted(values)


def github_urls(text: str) -> list[str]:
    found = {
        html.unescape(match.group(0)).rstrip(")]},;`\"'")
        for match in re.finditer(
            r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[0-9]+",
            text,
        )
    }
    return sorted(found)


def snippets(text: str, radius: int = 450) -> list[dict[str, str]]:
    lower = text.lower()
    found: list[dict[str, str]] = []
    for needle in NEEDLES:
        target = needle.lower()
        start = 0
        matches = 0
        while matches < 5:
            index = lower.find(target, start)
            if index < 0:
                break
            found.append(
                {
                    "needle": needle,
                    "snippet": text[
                        max(0, index - radius) : index + len(needle) + radius
                    ],
                }
            )
            matches += 1
            start = index + len(target)
    return found[:100]


def compact_response(response: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: response.get(key)
        for key in ("ok", "status", "url", "content_type", "bytes_read", "error")
        if response.get(key) is not None
    }
    if response.get("json") is not None:
        result["json"] = response["json"]
    elif isinstance(response.get("text"), str):
        text = response["text"]
        result["text_preview"] = text[:6000]
        result["github_issue_urls"] = github_urls(text)
        result["interesting_snippets"] = snippets(text)[:30]
    return result


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
            scripts[script_url] = {
                "ok": script.get("ok"),
                "status": script.get("status"),
                "content_type": script.get("content_type"),
                "bytes_read": script.get("bytes_read"),
                "github_issue_urls": github_urls(script_text),
                "interesting_snippets": snippets(script_text)[:40],
            }

    discovered_urls = extract_candidate_urls(combined, origin)
    endpoint_urls: set[str] = {origin + path for path in COMMON_ENDPOINTS}
    for url in discovered_urls:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc == urllib.parse.urlparse(origin).netloc and "/api/" in parsed.path:
            endpoint_urls.add(url)
    endpoint_results = {
        url: compact_response(request(url, 2_000_000))
        for url in sorted(endpoint_urls)[:80]
    }

    return {
        "name": name,
        "origin": origin,
        "pages": pages,
        "script_count": len(scripts),
        "scripts": scripts,
        "github_issue_urls": github_urls(combined),
        "candidate_urls": discovered_urls[:1500],
        "combined_snippets": snippets(combined)[:150],
        "endpoint_results": endpoint_results,
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
                    key: value.get("ok") for key, value in report["sites"].items()
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
