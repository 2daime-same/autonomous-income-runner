#!/usr/bin/env python3
"""Remove unnecessary sensitive identifiers from public marketplace snapshots.

Marketplace APIs can expose payment-session IDs, contact details, tokens, or
other fields that are not required to decide whether a bounty is actionable.
This sanitizer fail-closes: known-sensitive fields are replaced, URL query
secrets are stripped, and suspicious credential-looking values abort the run.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

INPUT = Path(os.environ.get("MARKET_SANITIZE_INPUT", "market-output/public-bounty-sites.json"))
OUTPUT = Path(os.environ.get("MARKET_SANITIZE_OUTPUT", str(INPUT)))

SENSITIVE_KEYS = {
    "access_token",
    "accessToken",
    "api_key",
    "apiKey",
    "authorization",
    "bearer",
    "bearer_token",
    "claim_code",
    "claimCode",
    "client_secret",
    "clientSecret",
    "contact_email",
    "contactEmail",
    "email",
    "email_address",
    "emailAddress",
    "password",
    "paypal_order_id",
    "paypalOrderId",
    "phone",
    "phone_number",
    "phoneNumber",
    "private_key",
    "privateKey",
    "refresh_token",
    "refreshToken",
    "secret",
    "seed_phrase",
    "seedPhrase",
    "session_id",
    "sessionId",
    "stripe_session_id",
    "stripeSessionId",
    "token",
    "wallet_signature",
    "walletSignature",
}

QUERY_SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "code",
    "key",
    "password",
    "secret",
    "session",
    "sig",
    "signature",
    "token",
}

CREDENTIAL_PATTERNS = [
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bcs_(?:live|test)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bpk_(?:live|test)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{20,}\b"),
]


def normalize_key(key: Any) -> str:
    return str(key).replace("-", "_").replace(" ", "").lower()


def sensitive_key(key: Any) -> bool:
    raw = str(key)
    normalized = normalize_key(key)
    return raw in SENSITIVE_KEYS or normalized in {
        normalize_key(value) for value in SENSITIVE_KEYS
    }


def sanitize_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    clean_query = [
        (key, "[REDACTED]" if key.lower() in QUERY_SECRET_KEYS else item)
        for key, item in query
    ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(clean_query, doseq=True),
            "",
        )
    )


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if sensitive_key(key_text):
                clean[key_text] = "[REDACTED]"
            else:
                clean[key_text] = sanitize(item)
        return clean
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return sanitize_url(value)
    return value


def find_credentials(value: Any, path: str = "$") -> list[str]:
    problems: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if sensitive_key(key) and item not in (None, "", "[REDACTED]"):
                problems.append(child)
            problems.extend(find_credentials(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            problems.extend(find_credentials(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        for pattern in CREDENTIAL_PATTERNS:
            if pattern.search(value):
                problems.append(path)
                break
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError:
            parsed = None
        if parsed and parsed.scheme in {"http", "https"}:
            for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
                if key.lower() in QUERY_SECRET_KEYS and item not in ("", "[REDACTED]"):
                    problems.append(f"{path}?{key}")
    return problems


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
    source = json.loads(INPUT.read_text(encoding="utf-8"))
    clean = sanitize(source)
    problems = find_credentials(clean)
    if problems:
        raise SystemExit(
            "Refusing to publish marketplace output containing credential-like data: "
            + ", ".join(sorted(set(problems))[:50])
        )
    atomic_write(OUTPUT, clean)
    print(json.dumps({"ok": True, "input": str(INPUT), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
