#!/usr/bin/env python3
"""Read-only GitHub bounty radar grounded in GitHub's own issue state.

The radar searches GitHub directly, extracts explicit reward evidence, checks
repository activity and open competing pull requests, and writes a compact
ranked candidate set. It never comments, claims, forks, submits, or pays.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
OUTPUT = Path(os.environ.get("GITHUB_BOUNTY_OUTPUT", "market-output/github-bounties.json"))
USER_AGENT = "nexaworks-autonomous-income-bounty-radar/1.0"
TIMEOUT = 45

MONEY_PATTERNS = [
    re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"),
    re.compile(r"(?:USD|USDC|USDT)\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I),
    re.compile(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:USD|USDC|USDT)\b", re.I),
    re.compile(r"£\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"),
    re.compile(r"€\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"),
]
REWARD_MARKERS = (
    "algora",
    "opire",
    "issuehunt",
    "bounty",
    "reward",
    "funded",
    "payment will be awarded",
    "receive payment",
)
BOT_LOGINS = {
    "algora-pbc[bot]",
    "opire-bot",
    "opire[bot]",
    "issuehunt[bot]",
    "github-actions[bot]",
}


class RadarError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiResponse:
    status: int
    data: Any
    headers: Mapping[str, str]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().replace(microsecond=0).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def api_get(path: str, params: Mapping[str, Any] | None = None, retries: int = 2) -> ApiResponse:
    url = path if path.startswith("https://") else API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    last: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read()
                data = json.loads(raw.decode("utf-8")) if raw else None
                return ApiResponse(response.status, data, dict(response.headers.items()))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail: Any = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw[:2000]
            if exc.code in {403, 429}:
                reset = exc.headers.get("X-RateLimit-Reset")
                if reset and attempt < retries:
                    delay = max(1, min(30, int(reset) - int(time.time()) + 1))
                    time.sleep(delay)
                    last = exc
                    continue
            if exc.code < 500 or attempt >= retries:
                raise RadarError(f"HTTP {exc.code} from {url}: {detail}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt >= retries:
                break
        time.sleep(2**attempt)
    raise RadarError(f"Request failed for {url}: {last}")


def extract_amounts(*texts: Any) -> list[float]:
    values: list[float] = []
    for raw in texts:
        if not isinstance(raw, str):
            continue
        for pattern in MONEY_PATTERNS:
            for match in pattern.finditer(raw):
                try:
                    value = float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
                if 0 < value <= 100_000:
                    values.append(value)
    return values


def label_names(issue: Mapping[str, Any]) -> list[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return []
    result = []
    for label in labels:
        if isinstance(label, Mapping) and isinstance(label.get("name"), str):
            result.append(label["name"])
        elif isinstance(label, str):
            result.append(label)
    return result


def repo_from_issue(issue: Mapping[str, Any]) -> str | None:
    repository_url = issue.get("repository_url")
    if not isinstance(repository_url, str):
        return None
    prefix = API + "/repos/"
    return repository_url[len(prefix) :] if repository_url.startswith(prefix) else None


def reward_evidence(issue: Mapping[str, Any], comments: list[Mapping[str, Any]]) -> dict[str, Any]:
    labels = label_names(issue)
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    comment_texts = [str(comment.get("body") or "") for comment in comments]
    amounts = extract_amounts(title, body, *labels, *comment_texts)

    marker_text = "\n".join([title, body, *labels, *comment_texts]).lower()
    explicit_markers = sorted({marker for marker in REWARD_MARKERS if marker in marker_text})
    bot_comments = []
    attempt_users: set[str] = set()
    reward_links = 0
    for comment in comments:
        login = str((comment.get("user") or {}).get("login") or "")
        text = str(comment.get("body") or "")
        lower = text.lower()
        if login.lower() in {value.lower() for value in BOT_LOGINS} or "bounty" in lower:
            bot_comments.append({"login": login, "excerpt": text[:1500]})
        if re.search(r"/(?:attempt|try)\b", lower):
            if login:
                attempt_users.add(login)
        reward_links += lower.count("[reward](")

    explicit_platform = any(
        marker in marker_text for marker in ("algora", "opire", "issuehunt")
    )
    funded_label = any("funded" in label.lower() or "bounty" in label.lower() for label in labels)
    max_amount = max(amounts) if amounts else 0.0
    return {
        "amounts": sorted(set(amounts)),
        "max_amount_usd": max_amount,
        "markers": explicit_markers,
        "explicit_platform": explicit_platform,
        "funded_or_bounty_label": funded_label,
        "bot_comments": bot_comments[:10],
        "attempt_users": sorted(attempt_users),
        "attempt_count": len(attempt_users),
        "reward_links_count": reward_links,
    }


def is_pr_reference(item: Mapping[str, Any]) -> bool:
    return isinstance(item.get("pull_request"), Mapping)


def search_issues(query: str, pages: int = 1) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        response = api_get(
            "/search/issues",
            {"q": query, "sort": "updated", "order": "desc", "per_page": 100, "page": page},
        )
        data = response.data
        if not isinstance(data, Mapping) or not isinstance(data.get("items"), list):
            raise RadarError("Unexpected GitHub search response")
        page_items = [item for item in data["items"] if isinstance(item, dict)]
        results.extend(page_items)
        if len(page_items) < 100:
            break
    return results


def fetch_comments(repo: str, number: int) -> list[dict[str, Any]]:
    response = api_get(f"/repos/{repo}/issues/{number}/comments", {"per_page": 100})
    return [item for item in response.data if isinstance(item, dict)] if isinstance(response.data, list) else []


def fetch_repo(repo: str) -> dict[str, Any]:
    response = api_get(f"/repos/{repo}")
    return response.data if isinstance(response.data, dict) else {}


def competing_prs(repo: str, number: int) -> list[dict[str, Any]]:
    # Search titles/bodies for either the issue URL or the canonical #number reference.
    queries = [
        f'repo:{repo} is:pr is:open "#{number}"',
        f'repo:{repo} is:pr is:open "issues/{number}"',
    ]
    found: dict[str, dict[str, Any]] = {}
    for query in queries:
        for item in search_issues(query):
            if is_pr_reference(item):
                found[str(item.get("html_url"))] = item
        if len(found) >= 10:
            break
    return [
        {
            "number": item.get("number"),
            "title": item.get("title"),
            "url": item.get("html_url"),
            "updated_at": item.get("updated_at"),
            "user": (item.get("user") or {}).get("login"),
        }
        for item in found.values()
    ]


def pre_score(issue: Mapping[str, Any]) -> float:
    amounts = extract_amounts(issue.get("title"), issue.get("body"), *label_names(issue))
    amount = max(amounts) if amounts else 0.0
    updated = parse_time(issue.get("updated_at"))
    age_days = (now_utc() - updated).days if updated else 9999
    comments = int(issue.get("comments") or 0)
    score = min(45.0, math.log10(max(1.0, amount)) * 15)
    score += max(0.0, 25.0 - min(25.0, age_days / 6))
    score += max(0.0, 15.0 - min(15.0, comments / 2))
    names = " ".join(label_names(issue)).lower()
    if "good first issue" in names:
        score += 8
    if "help wanted" in names:
        score += 5
    if "bounty" in names or "funded" in names:
        score += 8
    return score


def final_score(
    issue: Mapping[str, Any],
    evidence: Mapping[str, Any],
    repository: Mapping[str, Any],
    prs: list[Mapping[str, Any]],
) -> tuple[float, list[str]]:
    amount = float(evidence.get("max_amount_usd") or 0.0)
    updated = parse_time(issue.get("updated_at"))
    pushed = parse_time(repository.get("pushed_at"))
    age_days = (now_utc() - updated).days if updated else 9999
    push_age = (now_utc() - pushed).days if pushed else 9999
    comments = int(issue.get("comments") or 0)
    attempts = int(evidence.get("attempt_count") or 0)
    assignees = issue.get("assignees") if isinstance(issue.get("assignees"), list) else []

    score = 0.0
    reasons: list[str] = []
    if amount >= 1:
        score += min(35.0, 10 + math.log10(amount) * 10)
        reasons.append(f"explicit reward evidence up to ${amount:g}")
    if evidence.get("explicit_platform"):
        score += 15
        reasons.append("recognized bounty platform evidence")
    if evidence.get("funded_or_bounty_label"):
        score += 8
        reasons.append("repository bounty/funded label")
    if age_days <= 14:
        score += 18
        reasons.append("recently updated issue")
    elif age_days <= 60:
        score += 12
    elif age_days <= 180:
        score += 5
    else:
        score -= min(25, age_days / 30)
        reasons.append("old issue activity")
    if push_age <= 14:
        score += 12
        reasons.append("active repository")
    elif push_age <= 90:
        score += 6
    else:
        score -= 12
        reasons.append("repository not recently pushed")
    if not prs:
        score += 20
        reasons.append("no open competing PR found")
    else:
        score -= min(35, 12 * len(prs))
        reasons.append(f"{len(prs)} open competing PR(s)")
    if attempts == 0:
        score += 8
        reasons.append("no attempt command found")
    else:
        score -= min(25, attempts * 4)
        reasons.append(f"{attempts} attempt user(s)")
    if assignees:
        score -= 15
        reasons.append("issue already assigned")
    if comments <= 5:
        score += 5
    elif comments >= 30:
        score -= 10
    if repository.get("archived"):
        score -= 100
        reasons.append("repository archived")
    if issue.get("state") != "open":
        score -= 100
    if evidence.get("reward_links_count", 0) > 0:
        score -= 10
        reasons.append("existing reward links found; may be partially claimed")
    return round(score, 2), reasons


def main() -> int:
    since = (now_utc() - timedelta(days=240)).date().isoformat()
    queries = [
        f'is:issue is:open label:"💎 Bounty" updated:>={since}',
        f'is:issue is:open label:bounty updated:>={since}',
        f'is:issue is:open label:funded updated:>={since}',
        f'is:issue is:open in:title bounty updated:>={since}',
        f'is:issue is:open "IssueHunt" updated:>={since}',
        f'is:issue is:open "Opire Bounty" updated:>={since}',
        f'is:issue is:open "/bounty $" updated:>={since}',
        f'is:issue is:open "/reward " updated:>={since}',
    ]
    raw: dict[str, dict[str, Any]] = {}
    query_errors: list[dict[str, str]] = []
    for query in queries:
        try:
            for issue in search_issues(query):
                if is_pr_reference(issue):
                    continue
                url = str(issue.get("html_url") or "")
                if url:
                    raw[url] = issue
        except Exception as exc:
            query_errors.append({"query": query, "error": str(exc)})

    shortlist = sorted(raw.values(), key=pre_score, reverse=True)[:45]
    candidates: list[dict[str, Any]] = []
    repo_cache: dict[str, dict[str, Any]] = {}
    for issue in shortlist:
        repo = repo_from_issue(issue)
        number = issue.get("number")
        if not repo or not isinstance(number, int):
            continue
        try:
            comments = fetch_comments(repo, number)
            evidence = reward_evidence(issue, comments)
            if evidence["max_amount_usd"] < 1:
                continue
            repository = repo_cache.setdefault(repo, fetch_repo(repo))
            prs = competing_prs(repo, number)
            score, reasons = final_score(issue, evidence, repository, prs)
            candidates.append(
                {
                    "score": score,
                    "reasons": reasons,
                    "repo": repo,
                    "repo_language": repository.get("language"),
                    "repo_stars": repository.get("stargazers_count"),
                    "repo_archived": repository.get("archived"),
                    "repo_pushed_at": repository.get("pushed_at"),
                    "issue_number": number,
                    "title": issue.get("title"),
                    "url": issue.get("html_url"),
                    "created_at": issue.get("created_at"),
                    "updated_at": issue.get("updated_at"),
                    "comments_count": issue.get("comments"),
                    "assignees": [item.get("login") for item in issue.get("assignees", []) if isinstance(item, Mapping)],
                    "labels": label_names(issue),
                    "body_excerpt": str(issue.get("body") or "")[:6000],
                    "reward_evidence": evidence,
                    "open_competing_prs": prs,
                }
            )
        except Exception as exc:
            candidates.append(
                {
                    "score": -999,
                    "repo": repo,
                    "issue_number": number,
                    "title": issue.get("title"),
                    "url": issue.get("html_url"),
                    "inspection_error": str(exc),
                }
            )

    candidates.sort(key=lambda item: float(item.get("score") or -999), reverse=True)
    report = {
        "generated_at": iso_now(),
        "source": "GitHub REST Search and repository APIs",
        "search_since": since,
        "queries": queries,
        "query_errors": query_errors,
        "raw_unique_open_issues": len(raw),
        "deep_inspected": len(shortlist),
        "ranked_candidates": candidates,
        "recommended": [item for item in candidates if item.get("score", -999) >= 45][:20],
    }
    atomic_write(OUTPUT, report)
    print(json.dumps({"ok": True, "raw": len(raw), "ranked": len(candidates), "recommended": len(report["recommended"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
