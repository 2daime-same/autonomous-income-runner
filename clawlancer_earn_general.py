#!/usr/bin/env python3
"""Harden and reuse the Clawlancer executor for a non-welcome micro-bounty."""
from __future__ import annotations

import re
from typing import Any, Mapping

import clawlancer_earn as base

base.SECRET_KEYS.update({
    "auth_header",
    "heartbeat_config",
    "claim_url_template",
    "deliver_url_template",
})


def secure_sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.replace("-", "_").lower()
            result[key] = "[REDACTED]" if normalized in base.SECRET_KEYS else secure_sanitize(item)
        return result
    if isinstance(value, list):
        return [secure_sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Authorization:\s*Bearer\s+[^\s\"']+", "Authorization: Bearer [REDACTED]", value)
        value = re.sub(r"\b(?:clw|claw|cl|api)_[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)
        value = re.sub(r"\b0x[0-9a-fA-F]{64}\b", "[REDACTED_64_HEX]", value)
    return value


def choose_non_welcome(items: list[dict[str, Any]], agent_name: str) -> dict[str, Any] | None:
    safe: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("listing_type") or "").upper() != "BOUNTY":
            continue
        if item.get("is_active") is False or str(item.get("status") or "active").lower() not in {"active", "open"}:
            continue
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "")
        text = f"{title}\n{description}".lower()
        if "welcome to clawlancer" in text:
            continue
        if any(marker in text for marker in ("tweet", "post on x", "referral", "send usdc", "deposit", "purchase", "buy ")):
            continue
        try:
            price = int(item.get("price_wei") or 0)
        except (TypeError, ValueError):
            continue
        if not (0 < price <= 50_000):
            continue
        safe.append(item)

    priorities = (
        "draft an faq for new ai agents",
        "create a glossary of agent economy terms",
        "write a regex to validate ethereum addresses",
    )
    for wanted in priorities:
        matches = [item for item in safe if str(item.get("title") or "").strip().lower() == wanted]
        if matches:
            return sorted(matches, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]
    return None


base.sanitize = secure_sanitize
base.choose_listing = choose_non_welcome

if __name__ == "__main__":
    raise SystemExit(base.main())
