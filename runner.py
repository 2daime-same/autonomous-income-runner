#!/usr/bin/env python3
"""Isolated API runner for agent-eligible paid work.

Secrets are written only to ``.agent-state/superteam.json`` during execution.
The public-safe GitHub Actions workflow encrypts that file with the repository's
X.509 public certificate, deletes the plaintext, and commits only ciphertext
plus sanitized evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE_URL = "https://superteam.fun"
STATE_DIR = Path(os.environ.get("AGENT_STATE_DIR", ".agent-state"))
STATE_FILE = STATE_DIR / "superteam.json"
OUTPUT_DIR = Path(os.environ.get("AGENT_OUTPUT_DIR", "output"))
REQUEST_FILE = Path(os.environ.get("AGENT_REQUEST_FILE", "request.json"))
DEFAULT_TIMEOUT = 45
PUBLIC_SAFE_MODE = os.environ.get("PUBLIC_SAFE_MODE", "0") == "1"
SECRET_KEYS = {
    "access_token",
    "apikey",
    "api_key",
    "authorization",
    "bearertoken",
    "bearer_token",
    "claimcode",
    "claim_code",
    "human_privy_token",
    "privy_token",
    "refresh_token",
    "secret",
    "token",
}


class RunnerError(RuntimeError):
    """Expected operational error safe to show after sanitization."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write_json(path: Path, data: Any, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnerError(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RunnerError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunnerError(f"Expected a JSON object in {path}")
    return value


def sanitize(value: Any, *, reveal_claim: bool = False) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            if normalized in SECRET_KEYS:
                if reveal_claim and normalized in {"claimcode", "claim_code"}:
                    clean[key] = raw_value
                else:
                    clean[key] = "[REDACTED]"
            else:
                clean[key] = sanitize(raw_value, reveal_claim=reveal_claim)
        return clean
    if isinstance(value, list):
        return [sanitize(item, reveal_claim=reveal_claim) for item in value]
    return value


def http_json(
    method: str,
    path: str,
    *,
    body: Mapping[str, Any] | None = None,
    bearer: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 2,
) -> HttpResponse:
    url = path if path.startswith("https://") else f"{BASE_URL}{path}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "autonomous-income-runner/1.2",
    }
    payload: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url, data=payload, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
                if not raw:
                    data: Any = None
                elif "json" in content_type.lower():
                    data = json.loads(raw.decode("utf-8"))
                else:
                    text = raw.decode("utf-8", errors="replace")
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = {"text": text}
                return HttpResponse(status=response.status, data=data)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail: Any = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw[:2000]
            if exc.code < 500 or attempt >= retries:
                raise RunnerError(
                    f"HTTP {exc.code} from {url}: "
                    f"{json.dumps(sanitize(detail), ensure_ascii=False)}"
                ) from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                break
        time.sleep(2**attempt)
    raise RunnerError(f"Request failed for {url}: {last_error}")


def stable_agent_name(request: Mapping[str, Any]) -> str:
    requested = str(request.get("agentName") or "BoundaryLedger-Agent").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "local/runner")
    request_id = str(request.get("requestId") or "default")
    suffix = hashlib.sha256(f"{repo}:{request_id}".encode("utf-8")).hexdigest()[:8]
    return f"{requested}-{suffix}"[:50]


def state_from_environment() -> dict[str, Any] | None:
    api_key = os.environ.get("SUPERTEAM_API_KEY", "").strip()
    if not api_key:
        return None
    if not api_key.startswith("sk_"):
        raise RunnerError("SUPERTEAM_API_KEY does not have the expected sk_ prefix")
    state = {
        "apiKey": api_key,
        "claimCode": os.environ.get("SUPERTEAM_CLAIM_CODE", "").strip() or None,
        "agentId": os.environ.get("SUPERTEAM_AGENT_ID", "").strip() or None,
        "username": os.environ.get("SUPERTEAM_USERNAME", "").strip() or None,
        "registeredAt": os.environ.get("SUPERTEAM_REGISTERED_AT", "").strip()
        or utc_now(),
        "baseUrl": BASE_URL,
        "source": "environment",
    }
    atomic_write_json(STATE_FILE, state, mode=0o600)
    return state


def register_if_needed(request: Mapping[str, Any]) -> dict[str, Any]:
    environment_state = state_from_environment()
    if environment_state is not None:
        return environment_state

    if STATE_FILE.exists():
        state = read_json(STATE_FILE)
        api_key = state.get("apiKey")
        if isinstance(api_key, str) and api_key.startswith("sk_"):
            return state

    name = stable_agent_name(request)
    # Registration is non-idempotent. Never retry after an ambiguous timeout.
    response = http_json("POST", "/api/agents", body={"name": name}, retries=0)
    if response.status not in {200, 201} or not isinstance(response.data, dict):
        raise RunnerError(f"Unexpected registration response: HTTP {response.status}")
    api_key = response.data.get("apiKey")
    claim_code = response.data.get("claimCode")
    if not isinstance(api_key, str) or not api_key.startswith("sk_"):
        raise RunnerError("Registration response did not contain a valid apiKey")
    if not isinstance(claim_code, str) or not claim_code:
        raise RunnerError("Registration response did not contain a claimCode")

    state = dict(response.data)
    state["registeredAt"] = utc_now()
    state["baseUrl"] = BASE_URL
    state["source"] = "registration"
    atomic_write_json(STATE_FILE, state, mode=0o600)
    return state


def api_key_from(state: Mapping[str, Any]) -> str:
    value = state.get("apiKey")
    if not isinstance(value, str) or not value.startswith("sk_"):
        raise RunnerError("Agent state is missing a valid apiKey")
    return value


def operation_list(request: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    cfg = request.get("list") if isinstance(request.get("list"), dict) else {}
    take = max(1, min(int(cfg.get("take", 100)), 100))
    query: dict[str, str] = {"take": str(take)}
    for key in ("deadline", "type"):
        value = cfg.get(key)
        if value:
            query[key] = str(value)
    path = "/api/agents/listings/live?" + urllib.parse.urlencode(query)
    response = http_json("GET", path, bearer=api_key_from(state))
    return {
        "operation": "list",
        "fetchedAt": utc_now(),
        "httpStatus": response.status,
        "query": query,
        "data": response.data,
    }


def operation_details(request: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    slug = request.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        raise RunnerError("details operation requires a non-empty 'slug'")
    path = "/api/agents/listings/details/" + urllib.parse.quote(slug.strip(), safe="")
    response = http_json("GET", path, bearer=api_key_from(state))
    return {
        "operation": "details",
        "fetchedAt": utc_now(),
        "httpStatus": response.status,
        "slug": slug,
        "data": response.data,
    }


def operation_comments(request: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    listing_id = request.get("listingId")
    if not isinstance(listing_id, str) or not listing_id.strip():
        raise RunnerError("comments operation requires a non-empty 'listingId'")
    skip = max(0, int(request.get("skip", 0)))
    take = max(1, min(int(request.get("take", 50)), 100))
    path = (
        "/api/agents/comments/"
        + urllib.parse.quote(listing_id.strip(), safe="")
        + "?"
        + urllib.parse.urlencode({"skip": skip, "take": take})
    )
    response = http_json("GET", path, bearer=api_key_from(state))
    return {
        "operation": "comments",
        "fetchedAt": utc_now(),
        "httpStatus": response.status,
        "listingId": listing_id,
        "data": response.data,
    }


def operation_comment_create(
    request: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, Any]:
    comment = request.get("comment")
    if not isinstance(comment, dict):
        raise RunnerError("comment_create requires a 'comment' JSON object")
    required = ["refType", "refId", "message", "pocId"]
    missing = [key for key in required if not comment.get(key)]
    if missing:
        raise RunnerError(f"Comment is missing required fields: {', '.join(missing)}")
    payload = {
        "refType": comment["refType"],
        "refId": comment["refId"],
        "message": comment["message"],
        "pocId": comment["pocId"],
    }
    for key in ("replyToId", "replyToUserId"):
        if comment.get(key):
            payload[key] = comment[key]
    response = http_json(
        "POST",
        "/api/agents/comments/create",
        body=payload,
        bearer=api_key_from(state),
        retries=0,
    )
    return {
        "operation": "comment_create",
        "submittedAt": utc_now(),
        "httpStatus": response.status,
        "refId": comment["refId"],
        "data": response.data,
    }


def submission_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    submission = request.get("submission")
    if not isinstance(submission, dict):
        raise RunnerError("submission operation requires a 'submission' JSON object")
    listing_id = submission.get("listingId")
    other_info = submission.get("otherInfo")
    link = submission.get("link", "")
    if not listing_id:
        raise RunnerError("Submission is missing required field: listingId")
    if not other_info and not link:
        raise RunnerError("Submission requires a link or detailed otherInfo")
    answers = submission.get("eligibilityAnswers", [])
    if not isinstance(answers, list):
        raise RunnerError("eligibilityAnswers must be an array")
    return {
        "listingId": listing_id,
        "link": link,
        "tweet": submission.get("tweet", ""),
        "otherInfo": other_info or "",
        "eligibilityAnswers": answers,
        "ask": submission.get("ask"),
        "telegram": submission.get("telegram", ""),
    }


def operation_submission_write(
    operation: str, request: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, Any]:
    payload = submission_payload(request)
    endpoint = (
        "/api/agents/submissions/create"
        if operation == "submit"
        else "/api/agents/submissions/update"
    )
    response = http_json(
        "POST",
        endpoint,
        body=payload,
        bearer=api_key_from(state),
        retries=0,
    )
    return {
        "operation": operation,
        "submittedAt": utc_now(),
        "httpStatus": response.status,
        "listingId": payload["listingId"],
        "data": response.data,
    }


def operation_reveal_claim(state: Mapping[str, Any]) -> dict[str, Any]:
    if PUBLIC_SAFE_MODE or os.environ.get("ALLOW_SECRET_OUTPUT") != "1":
        raise RunnerError(
            "Claim-code output is disabled. Decrypt the encrypted state in a private environment."
        )
    return {
        "operation": "reveal_claim",
        "generatedAt": utc_now(),
        "claimCode": state.get("claimCode"),
        "claimUrl": f"{BASE_URL}/earn/claim/{state.get('claimCode', '')}",
        "agentId": state.get("agentId"),
        "username": state.get("username"),
    }


def execute(request: Mapping[str, Any]) -> dict[str, Any]:
    state = register_if_needed(request)
    operation = str(request.get("operation") or "list").lower()
    if operation == "list":
        result = operation_list(request, state)
    elif operation == "details":
        result = operation_details(request, state)
    elif operation == "comments":
        result = operation_comments(request, state)
    elif operation == "comment_create":
        result = operation_comment_create(request, state)
    elif operation in {"submit", "update_submission"}:
        result = operation_submission_write(operation, request, state)
    elif operation == "reveal_claim":
        result = operation_reveal_claim(state)
    else:
        raise RunnerError(f"Unsupported operation: {operation}")

    reveal_claim = operation == "reveal_claim" and not PUBLIC_SAFE_MODE
    public_agent = {
        "agentId": state.get("agentId"),
        "username": state.get("username"),
        "registeredAt": state.get("registeredAt"),
        "baseUrl": state.get("baseUrl"),
        "source": state.get("source"),
        "claimCode": state.get("claimCode") if reveal_claim else "[REDACTED]",
    }
    atomic_write_json(OUTPUT_DIR / "agent-public.json", public_agent)
    atomic_write_json(
        OUTPUT_DIR / "latest.json",
        sanitize(result, reveal_claim=reveal_claim),
        mode=0o600 if reveal_claim else 0o644,
    )
    atomic_write_json(
        OUTPUT_DIR / "run-summary.json",
        {
            "ok": True,
            "operation": operation,
            "completedAt": utc_now(),
            "resultFile": "output/latest.json",
            "privateState": "output/private-state.cms when registration state exists",
        },
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, default=REQUEST_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        request = read_json(args.request)
        if args.dry_run:
            print(json.dumps({"ok": True, "request": sanitize(request)}, indent=2))
            return 0
        result = execute(request)
        print(json.dumps({"ok": True, "result": sanitize(result)}, ensure_ascii=False))
        return 0
    except RunnerError as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            OUTPUT_DIR / "run-summary.json",
            {"ok": False, "failedAt": utc_now(), "error": str(exc)},
        )
        print(f"runner error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
