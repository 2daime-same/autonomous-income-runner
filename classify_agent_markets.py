#!/usr/bin/env python3
"""Classify probed agent marketplaces into zero-spend execution readiness.

This script only reads previously captured public evidence. It never contacts or
mutates a marketplace.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

OUTPUT = Path("market-output/agent-market-readiness.json")
ONE_LINE = Path("market-output/agent-market-readiness.txt")


def load(path: str) -> Any:
    file = Path(path)
    if not file.exists():
        return None
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return None


def flatten(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False).lower()
    except Exception:
        return str(value).lower()


def route_strings(value: Any) -> list[str]:
    routes: list[str] = []
    if isinstance(value, Mapping):
        if isinstance(value.get("routes"), list):
            for route in value["routes"]:
                if isinstance(route, Mapping):
                    routes.append(f"{route.get('method','')} {route.get('url','')}")
        for item in value.values():
            routes.extend(route_strings(item))
    elif isinstance(value, list):
        for item in value:
            routes.extend(route_strings(item))
    return routes


def evidence(text: str, routes: list[str], patterns: list[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        regex = re.compile(pattern, re.I)
        for route in routes:
            if regex.search(route):
                matches.append(route[:300])
        if regex.search(text):
            matches.append(f"text:{pattern}")
    return sorted(set(matches))[:20]


def classify(name: str, value: Any) -> dict[str, Any]:
    text = flatten(value)
    routes = route_strings(value)
    result = {
        "name": name,
        "evidence_present": value is not None,
        "route_count": len(routes),
        "registration": evidence(text, routes, [r"register", r"signup", r"/agents?$"]),
        "inventory": evidence(text, routes, [r"tasks?", r"jobs?", r"missions?", r"bount", r"marketplace"]),
        "apply_or_claim": evidence(text, routes, [r"apply", r"claim", r"accept", r"bid"]),
        "delivery": evidence(text, routes, [r"deliver", r"submit", r"solution", r"artifact"]),
        "payout": evidence(text, routes, [r"payout", r"earnings?", r"balance", r"settle", r"withdraw", r"usdc", r"wallet"]),
        "cost_or_deposit": evidence(text, routes, [r"deposit", r"stake", r"registration fee", r"worker fee", r"gas fee", r"pay to", r"purchase"]),
        "auth_or_identity": evidence(text, routes, [r"email verif", r"kyc", r"api.?key", r"wallet sign", r"signature", r"oauth"]),
    }
    required = ["registration", "inventory", "apply_or_claim", "delivery", "payout"]
    result["complete_execution_contract"] = all(bool(result[key]) for key in required)
    result["zero_spend_safe"] = result["complete_execution_contract"] and not bool(result["cost_or_deposit"])
    if not value:
        result["decision"] = "no_evidence"
    elif result["zero_spend_safe"]:
        result["decision"] = "implement_worker"
    elif result["complete_execution_contract"] and result["cost_or_deposit"]:
        result["decision"] = "exclude_cost_or_deposit"
    else:
        missing = [key for key in required if not result[key]]
        result["decision"] = "incomplete_contract:" + ",".join(missing)
    return result


def main() -> int:
    tetto_hyrve = load("market-output/tetto-hyrve-contract.json") or {}
    markets = tetto_hyrve.get("markets") if isinstance(tetto_hyrve, Mapping) else {}
    values = {
        "tetto": markets.get("tetto") if isinstance(markets, Mapping) else None,
        "hyrve": markets.get("hyrve") if isinstance(markets, Mapping) else None,
        "aigen": load("market-output/aigen-contract.json"),
        "agenticgateway_supplier": {
            "summary": load("market-output/agenticgateway-supplier-contract.json"),
            "skill": Path("market-output/agenticgateway-supplier-skill.md").read_text(encoding="utf-8")
            if Path("market-output/agenticgateway-supplier-skill.md").exists()
            else "",
        },
    }
    results = {name: classify(name, value) for name, value in values.items()}
    ready = sorted(name for name, result in results.items() if result["decision"] == "implement_worker")
    excluded = sorted(name for name, result in results.items() if result["decision"] == "exclude_cost_or_deposit")
    report = {
        "results": results,
        "ready_for_zero_spend_worker": ready,
        "excluded_for_cost_or_deposit": excluded,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)
    line = "ready=" + (",".join(ready) or "none") + ";excluded_cost=" + (",".join(excluded) or "none") + ";decisions=" + ",".join(f"{name}:{results[name]['decision']}" for name in sorted(results))
    ONE_LINE.write_text(line + "\n", encoding="utf-8")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
