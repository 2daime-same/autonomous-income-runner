#!/usr/bin/env python3
"""Resolve zero-spend marketplace execution plans from captured official docs.

The resolver uses GitHub Models only to structure already-captured public text.
Every mutation endpoint must be found verbatim in that evidence before a plan can
be marked actionable. No marketplace call is made by this script.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

MODEL = os.environ.get("MARKET_RESOLVER_MODEL", "openai/gpt-4.1-mini")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUTPUT = Path("market-output/market-execution-plans.json")
SUMMARY = Path("market-output/market-execution-plans.txt")
SOURCES = {
    "tetto": [
        "market-output/tetto-hyrve-contract.json",
        "market-output/tetto-hyrve-docs.txt",
    ],
    "hyrve": [
        "market-output/tetto-hyrve-contract.json",
        "market-output/tetto-hyrve-docs.txt",
    ],
    "aigen": [
        "market-output/aigen-contract.json",
        "market-output/aigen-docs.txt",
    ],
}
DISALLOWED_TEXT = re.compile(
    r"(deposit|stake|registration fee|worker fee|claim fee|purchase required|"
    r"send funds|pay first|credit card required|private key|seed phrase|"
    r"captcha|kyc required|social media post|required referral)",
    re.I,
)
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH"}
REQUIRED_STAGES = ("register", "inventory", "claim_or_apply", "deliver", "earnings")


def read_text(path: str) -> str:
    file = Path(path)
    if not file.exists():
        return ""
    return file.read_text(encoding="utf-8", errors="replace")[:1_500_000]


def source_text(name: str) -> str:
    parts = [read_text(path) for path in SOURCES[name]]
    text = "\n\n".join(parts)
    if name in {"tetto", "hyrve"}:
        # Preserve only the named market's likely regions where possible while
        # retaining route evidence from the full capture.
        return f"MARKET={name}\n" + text
    return text


def github_model(system: str, user: str, max_tokens: int = 5000) -> str | None:
    if not TOKEN:
        return None
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:100_000]},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    for attempt in range(4):
        request = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {TOKEN}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "boundaryledger-market-plan-resolver/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
                content = payload.get("choices", [{}])[0].get("message", {}).get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        except Exception:
            import time

            time.sleep(2**attempt)
    return None


def parse_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    return json.loads(stripped)


def normalize_endpoint(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    method = str(value.get("method") or "").upper()
    url = str(value.get("url") or value.get("path") or "").strip()
    if not method or not url:
        return None
    return {
        "method": method,
        "url": url,
        "auth": str(value.get("auth") or "none"),
        "headers": value.get("headers") if isinstance(value.get("headers"), Mapping) else {},
        "body": value.get("body") if isinstance(value.get("body"), Mapping) else {},
        "response_fields": value.get("response_fields") if isinstance(value.get("response_fields"), list) else [],
    }


def endpoint_in_evidence(endpoint: Mapping[str, Any], evidence: str) -> bool:
    method = str(endpoint.get("method") or "").upper()
    url = str(endpoint.get("url") or "")
    if method not in ALLOWED_METHODS or not url:
        return False
    parsed_path = url
    if url.startswith("http"):
        from urllib.parse import urlparse

        parsed_path = urlparse(url).path
    candidates = {url, parsed_path}
    # Tolerate path variables but require surrounding literal path segments.
    for candidate in candidates:
        literal = re.sub(r"\{[^}]+\}", "", candidate).rstrip("/")
        if len(literal) >= 4 and literal.lower() in evidence.lower():
            return True
    return False


def safe_template(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False)
    return not DISALLOWED_TEXT.search(text)


def resolve_one(name: str, evidence: str) -> dict[str, Any]:
    evidence_hash = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    prompt = {
        "market": name,
        "task": (
            "Extract a zero-spend worker execution contract from the evidence. "
            "Do not infer endpoints or request fields. Use null when absent."
        ),
        "required_output": {
            "market": name,
            "base_url": "official HTTPS API origin or null",
            "explicit_zero_worker_fee": "true/false/null",
            "requires_deposit_or_stake": "true/false/null",
            "requires_human_identity_or_email_click": "true/false/null",
            "wallet_or_payout_notes": "string",
            "current_inventory_evidence": "string",
            "register": {"method": "", "url": "", "auth": "", "headers": {}, "body": {}, "response_fields": []},
            "inventory": {"method": "", "url": "", "auth": "", "headers": {}, "body": {}, "response_fields": []},
            "claim_or_apply": {"method": "", "url": "", "auth": "", "headers": {}, "body": {}, "response_fields": []},
            "deliver": {"method": "", "url": "", "auth": "", "headers": {}, "body": {}, "response_fields": []},
            "earnings": {"method": "", "url": "", "auth": "", "headers": {}, "body": {}, "response_fields": []},
            "evidence_quotes": ["short paraphrased evidence labels, no long quotes"],
        },
    }
    system = (
        "You are a strict API contract extractor. Return one JSON object only. "
        "Extract only facts literally supported by the supplied official capture. "
        "Never invent an endpoint, HTTP method, body field, auth header, fee, or payout rule. "
        "An empty or missing stage must be represented by null. "
        "Distinguish buyer APIs from worker/supplier APIs."
    )
    response = github_model(system, json.dumps(prompt, ensure_ascii=False) + "\n\nEVIDENCE:\n" + evidence)
    raw: dict[str, Any]
    try:
        parsed = parse_json(response or "")
        raw = dict(parsed) if isinstance(parsed, Mapping) else {}
    except Exception:
        raw = {}

    normalized: dict[str, Any] = {
        "market": name,
        "evidence_sha256": evidence_hash,
        "base_url": raw.get("base_url"),
        "explicit_zero_worker_fee": raw.get("explicit_zero_worker_fee"),
        "requires_deposit_or_stake": raw.get("requires_deposit_or_stake"),
        "requires_human_identity_or_email_click": raw.get("requires_human_identity_or_email_click"),
        "wallet_or_payout_notes": str(raw.get("wallet_or_payout_notes") or "")[:2000],
        "current_inventory_evidence": str(raw.get("current_inventory_evidence") or "")[:2000],
        "evidence_quotes": [str(item)[:500] for item in raw.get("evidence_quotes", [])[:20]]
        if isinstance(raw.get("evidence_quotes"), list)
        else [],
        "stages": {},
    }
    missing: list[str] = []
    invalid: list[str] = []
    for stage in REQUIRED_STAGES:
        endpoint = normalize_endpoint(raw.get(stage))
        if endpoint is None:
            normalized["stages"][stage] = None
            missing.append(stage)
            continue
        endpoint["evidence_verified"] = endpoint_in_evidence(endpoint, evidence)
        endpoint["template_safe"] = safe_template(endpoint)
        normalized["stages"][stage] = endpoint
        if not endpoint["evidence_verified"] or not endpoint["template_safe"]:
            invalid.append(stage)

    deposit_flag = normalized["requires_deposit_or_stake"] is True
    zero_fee_flag = normalized["explicit_zero_worker_fee"] is True
    human_gate = normalized["requires_human_identity_or_email_click"] is True
    normalized["missing_stages"] = missing
    normalized["invalid_stages"] = invalid
    normalized["actionable"] = (
        not missing
        and not invalid
        and not deposit_flag
        and zero_fee_flag
        and not human_gate
        and isinstance(normalized.get("base_url"), str)
        and str(normalized["base_url"]).startswith("https://")
    )
    if normalized["actionable"]:
        normalized["decision"] = "implement_zero_spend_worker"
    elif deposit_flag:
        normalized["decision"] = "exclude_deposit_or_stake"
    elif human_gate:
        normalized["decision"] = "human_gate"
    else:
        normalized["decision"] = "insufficient_verified_contract"
    return normalized


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def main() -> int:
    results = {name: resolve_one(name, source_text(name)) for name in SOURCES}
    actionable = [name for name, item in results.items() if item.get("actionable")]
    report = {"results": results, "actionable_markets": actionable}
    atomic_json(OUTPUT, report)
    line = "actionable=" + (",".join(actionable) or "none") + ";" + ",".join(
        f"{name}:{results[name]['decision']}" for name in sorted(results)
    )
    SUMMARY.write_text(line + "\n", encoding="utf-8")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
