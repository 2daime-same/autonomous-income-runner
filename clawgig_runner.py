#!/usr/bin/env python3
"""Owner-only ClawGig API runner for the autonomous income mission.

Private API credentials and operator claim material are written only under
``.clawgig-state``. GitHub Actions caches that directory and commits only
sanitized JSON plus CMS-encrypted recovery state.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

BASE_URL = "https://clawgig.ai/api/v1"
STATE_DIR = Path(os.environ.get("CLAWGIG_STATE_DIR", ".clawgig-state"))
STATE_FILE = STATE_DIR / "state.json"
OUTPUT_DIR = Path(os.environ.get("CLAWGIG_OUTPUT_DIR", "clawgig/output"))
REQUEST_FILE = Path(os.environ.get("CLAWGIG_REQUEST_FILE", "clawgig/request.json"))
DEFAULT_TIMEOUT = 45

SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "claim_token",
    "claim_url",
    "contact_email",
    "email",
    "refresh_token",
    "secret",
    "token",
    "wallet_private_key",
    "webhook_secret",
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


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            if normalized in SECRET_KEYS:
                clean[key] = "[REDACTED]"
            else:
                clean[key] = sanitize(raw_value)
        return clean
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        if value.startswith(("cg_", "whsec_")):
            return "[REDACTED]"
        if re.fullmatch(r"\d{6}", value):
            return "[REDACTED_CODE]"
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
        "User-Agent": "nexaworks-autonomous-income-runner/1.0",
    }
    payload: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
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


def api_key_from(state: Mapping[str, Any]) -> str:
    value = state.get("api_key")
    if not isinstance(value, str) or not value.startswith("cg_"):
        raise RunnerError("ClawGig state is missing a valid api_key")
    return value


def load_state() -> dict[str, Any] | None:
    if not STATE_FILE.exists():
        return None
    state = read_json(STATE_FILE)
    api_key_from(state)
    return state


def registration_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    profile = request.get("profile")
    if not isinstance(profile, dict):
        raise RunnerError("register operation requires a profile object")
    required = [
        "name",
        "username",
        "description",
        "skills",
        "categories",
        "webhook_url",
        "avatar_url",
        "contact_email",
        "languages",
    ]
    missing = [key for key in required if not profile.get(key)]
    if missing:
        raise RunnerError(f"Profile is missing required fields: {', '.join(missing)}")
    payload = {key: profile[key] for key in required}
    if profile.get("hourly_rate_usdc") is not None:
        payload["hourly_rate_usdc"] = profile["hourly_rate_usdc"]
    return payload


def register_if_needed(request: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    state = load_state()
    if state is not None:
        return state, False

    payload = registration_payload(request)
    response = http_json("POST", "/agents/register", body=payload, retries=0)
    if response.status not in {200, 201} or not isinstance(response.data, dict):
        raise RunnerError(f"Unexpected registration response: HTTP {response.status}")
    api_key = response.data.get("api_key")
    claim_url = response.data.get("claim_url")
    if not isinstance(api_key, str) or not api_key.startswith("cg_"):
        raise RunnerError("Registration response did not contain a valid api_key")
    if not isinstance(claim_url, str) or not claim_url.startswith("https://"):
        raise RunnerError("Registration response did not contain a valid claim_url")

    state = dict(response.data)
    state["registered_at"] = utc_now()
    state["contact_email"] = payload["contact_email"]
    state["username"] = payload["username"]
    state["base_url"] = BASE_URL
    atomic_write_json(STATE_FILE, state, mode=0o600)
    return state, True


def auth_json(
    state: Mapping[str, Any],
    method: str,
    path: str,
    *,
    body: Mapping[str, Any] | None = None,
    retries: int = 2,
) -> HttpResponse:
    return http_json(
        method,
        path,
        body=body,
        bearer=api_key_from(state),
        retries=retries,
    )


def get_readiness(state: Mapping[str, Any]) -> Any:
    return auth_json(state, "GET", "/agents/me/readiness").data


def ensure_portfolio(state: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    existing = auth_json(state, "GET", "/agents/me/portfolio").data
    items: Sequence[Any]
    if isinstance(existing, dict) and isinstance(existing.get("data"), list):
        items = existing["data"]
    elif isinstance(existing, list):
        items = existing
    else:
        items = []
    if items:
        return {"created": False, "count": len(items)}

    portfolio = request.get("portfolio")
    if not isinstance(portfolio, dict) or not portfolio.get("title"):
        raise RunnerError("At least one portfolio item is required")
    response = auth_json(
        state,
        "POST",
        "/agents/me/portfolio",
        body=portfolio,
        retries=0,
    )
    return {"created": True, "item": response.data}


def list_gigs(state: Mapping[str, Any], request: Mapping[str, Any]) -> Any:
    cfg = request.get("gigs") if isinstance(request.get("gigs"), dict) else {}
    query: dict[str, str] = {
        "limit": str(max(1, min(int(cfg.get("limit", 50)), 50))),
        "offset": str(max(0, int(cfg.get("offset", 0)))),
        "sort": str(cfg.get("sort") or "newest"),
    }
    for key in ("category", "skills", "q"):
        value = cfg.get(key)
        if value:
            query[key] = str(value)
    for key in ("min_budget", "max_budget"):
        value = cfg.get(key)
        if value is not None:
            query[key] = str(float(value))
    path = "/gigs?" + urllib.parse.urlencode(query)
    return auth_json(state, "GET", path).data


def send_verification_email(state: Mapping[str, Any]) -> Any:
    email = state.get("contact_email")
    if not isinstance(email, str) or "@" not in email:
        raise RunnerError("State is missing a contact email")
    response = auth_json(
        state,
        "POST",
        "/agents/me/verify-email",
        body={"email": email},
        retries=0,
    )
    state = dict(state)
    state["verification_requested_at"] = utc_now()
    atomic_write_json(STATE_FILE, state, mode=0o600)
    return response.data


def confirm_verification(state: Mapping[str, Any]) -> Any:
    code = os.environ.get("CLAWGIG_VERIFY_CODE", "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise RunnerError("CLAWGIG_VERIFY_CODE must contain exactly six digits")
    response = auth_json(
        state,
        "POST",
        "/agents/me/verify-email/confirm",
        body={"code": code},
        retries=0,
    )
    state = dict(state)
    state["email_verified_at"] = utc_now()
    atomic_write_json(STATE_FILE, state, mode=0o600)
    return response.data


def proposal_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    required = ["gig_id", "cover_letter", "proposed_amount_usdc"]
    missing = [key for key in required if item.get(key) in (None, "")]
    if missing:
        raise RunnerError(f"Proposal is missing required fields: {', '.join(missing)}")
    payload: dict[str, Any] = {
        "cover_letter": str(item["cover_letter"]),
        "proposed_amount_usdc": float(item["proposed_amount_usdc"]),
    }
    if item.get("estimated_hours") is not None:
        payload["estimated_hours"] = float(item["estimated_hours"])
    if len(payload["cover_letter"]) < 20:
        raise RunnerError("Proposal cover_letter must be at least 20 characters")
    if payload["proposed_amount_usdc"] <= 0:
        raise RunnerError("Proposal amount must be positive")
    return payload


def submit_proposals(state: Mapping[str, Any], request: Mapping[str, Any]) -> list[Any]:
    readiness = get_readiness(state)
    if not isinstance(readiness, dict) or readiness.get("ready") is not True:
        raise RunnerError("Agent is not ready to submit proposals")
    proposals = request.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        raise RunnerError("propose operation requires a non-empty proposals array")
    results: list[Any] = []
    for raw in proposals:
        if not isinstance(raw, dict):
            raise RunnerError("Each proposal must be a JSON object")
        gig_id = str(raw.get("gig_id") or "").strip()
        payload = proposal_payload(raw)
        details = auth_json(state, "GET", f"/gigs/{urllib.parse.quote(gig_id, safe='')}").data
        if not isinstance(details, dict) or details.get("status") != "open":
            raise RunnerError(f"Gig {gig_id} is not open")
        budget = details.get("budget_usdc")
        if isinstance(budget, (int, float)) and payload["proposed_amount_usdc"] > float(budget):
            raise RunnerError(f"Proposal exceeds gig budget for {gig_id}")
        response = auth_json(
            state,
            "POST",
            f"/gigs/{urllib.parse.quote(gig_id, safe='')}/proposals",
            body=payload,
            retries=0,
        )
        results.append({"gig": details, "proposal": response.data})
    return results


def operation_register(request: Mapping[str, Any]) -> dict[str, Any]:
    state, created = register_if_needed(request)
    portfolio = ensure_portfolio(state, request)
    verification = send_verification_email(state)
    readiness = get_readiness(state)
    private_registration = {
        "agent_id": state.get("agent_id"),
        "api_key": state.get("api_key"),
        "claim_token": state.get("claim_token"),
        "claim_url": state.get("claim_url"),
        "contact_email": state.get("contact_email"),
        "username": state.get("username"),
        "registered_at": state.get("registered_at"),
    }
    atomic_write_json(OUTPUT_DIR / "private-registration.json", private_registration, mode=0o600)
    return {
        "operation": "register",
        "completed_at": utc_now(),
        "created": created,
        "agent_id": state.get("agent_id"),
        "username": state.get("username"),
        "claim_required": True,
        "email_verification_requested": True,
        "portfolio": portfolio,
        "verification_response": verification,
        "readiness": readiness,
    }


def operation_confirm(request: Mapping[str, Any]) -> dict[str, Any]:
    state = load_state()
    if state is None:
        raise RunnerError("No cached ClawGig registration state is available")
    confirmation = confirm_verification(state)
    portfolio = ensure_portfolio(state, request)
    readiness = get_readiness(state)
    gigs = list_gigs(state, request)
    return {
        "operation": "confirm",
        "completed_at": utc_now(),
        "email_confirmation": confirmation,
        "portfolio": portfolio,
        "readiness": readiness,
        "gigs": gigs,
    }


def operation_status(request: Mapping[str, Any]) -> dict[str, Any]:
    state = load_state()
    if state is None:
        raise RunnerError("No cached ClawGig registration state is available")
    profile = auth_json(state, "GET", "/agents/me").data
    readiness = get_readiness(state)
    gigs = list_gigs(state, request)
    proposals = auth_json(state, "GET", "/agents/me/proposals").data
    return {
        "operation": "status",
        "completed_at": utc_now(),
        "profile": profile,
        "readiness": readiness,
        "gigs": gigs,
        "proposals": proposals,
    }


def operation_propose(request: Mapping[str, Any]) -> dict[str, Any]:
    state = load_state()
    if state is None:
        raise RunnerError("No cached ClawGig registration state is available")
    results = submit_proposals(state, request)
    return {
        "operation": "propose",
        "completed_at": utc_now(),
        "submitted": results,
    }


def execute(request: Mapping[str, Any]) -> dict[str, Any]:
    operation = str(request.get("operation") or "status").lower()
    if operation == "register":
        result = operation_register(request)
    elif operation == "confirm":
        result = operation_confirm(request)
    elif operation == "status":
        result = operation_status(request)
    elif operation == "propose":
        result = operation_propose(request)
    else:
        raise RunnerError(f"Unsupported operation: {operation}")

    atomic_write_json(OUTPUT_DIR / "latest.json", sanitize(result))
    atomic_write_json(
        OUTPUT_DIR / "run-summary.json",
        {
            "ok": True,
            "operation": operation,
            "completed_at": utc_now(),
            "result_file": "clawgig/output/latest.json",
            "private_state": "clawgig/output/private-state.cms",
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
            registration_payload(request) if request.get("operation") == "register" else None
            print(json.dumps({"ok": True, "request": sanitize(request)}, indent=2))
            return 0
        result = execute(request)
        print(json.dumps({"ok": True, "result": sanitize(result)}, ensure_ascii=False))
        return 0
    except RunnerError as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            OUTPUT_DIR / "run-summary.json",
            {"ok": False, "failed_at": utc_now(), "error": str(exc)},
        )
        print(f"runner error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
