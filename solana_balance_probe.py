#!/usr/bin/env python3
"""Read-only Solana balance monitor for externally verifiable income receipts.

The monitor uses only a public wallet address. It never loads or needs a private
key, never signs transactions, and never sends funds. A repository snapshot is
rewritten only when the observed balances change, so scheduled checks do not
create empty commits.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

WALLET = os.environ.get(
    "SOLANA_PUBLIC_WALLET",
    "4RYaiFeSQtZMFREZPuoER8wr5F2eDFs3XeDKtEqpgVaj",
).strip()
OUTPUT = Path(os.environ.get("SOLANA_BALANCE_OUTPUT", "income-output/solana-balance.json"))
RPC_URLS = [
    value.strip()
    for value in os.environ.get(
        "SOLANA_RPC_URLS",
        "https://api.mainnet-beta.solana.com",
    ).split(",")
    if value.strip()
]
TOKEN_PROGRAMS = {
    "spl-token": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "token-2022": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}
USDC_MAINNET_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TIMEOUT = 45


class ProbeError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def rpc_call(url: str, method: str, params: list[Any], request_id: int) -> Any:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "autonomous-income-runner-solana-balance/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ProbeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProbeError(f"RPC request failed for {url}: {exc}") from exc
    if not isinstance(body, Mapping):
        raise ProbeError(f"Unexpected JSON-RPC response from {url}")
    if body.get("error") is not None:
        raise ProbeError(f"RPC error from {url}: {body['error']}")
    return body.get("result")


def fetch_snapshot(url: str) -> dict[str, Any]:
    balance_result = rpc_call(url, "getBalance", [WALLET, {"commitment": "confirmed"}], 1)
    if not isinstance(balance_result, Mapping):
        raise ProbeError("getBalance returned an unexpected result")
    lamports = int(balance_result.get("value") or 0)

    token_accounts: list[dict[str, Any]] = []
    for index, (program_name, program_id) in enumerate(TOKEN_PROGRAMS.items(), start=2):
        result = rpc_call(
            url,
            "getTokenAccountsByOwner",
            [
                WALLET,
                {"programId": program_id},
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ],
            index,
        )
        values = result.get("value", []) if isinstance(result, Mapping) else []
        if not isinstance(values, list):
            continue
        for account in values:
            if not isinstance(account, Mapping):
                continue
            account_data = account.get("account")
            data = account_data.get("data") if isinstance(account_data, Mapping) else None
            parsed = data.get("parsed") if isinstance(data, Mapping) else None
            info = parsed.get("info") if isinstance(parsed, Mapping) else None
            if not isinstance(info, Mapping):
                continue
            token_amount = info.get("tokenAmount")
            if not isinstance(token_amount, Mapping):
                continue
            raw_amount = str(token_amount.get("amount") or "0")
            try:
                raw_integer = int(raw_amount)
            except ValueError:
                continue
            decimals = int(token_amount.get("decimals") or 0)
            ui_amount_string = str(
                token_amount.get("uiAmountString")
                if token_amount.get("uiAmountString") is not None
                else raw_integer / (10**decimals)
            )
            if raw_integer <= 0:
                continue
            token_accounts.append(
                {
                    "program": program_name,
                    "account": account.get("pubkey"),
                    "mint": info.get("mint"),
                    "raw_amount": raw_amount,
                    "decimals": decimals,
                    "ui_amount_string": ui_amount_string,
                }
            )

    token_accounts.sort(
        key=lambda item: (str(item.get("mint")), str(item.get("account")))
    )
    usdc_raw = sum(
        int(item["raw_amount"])
        for item in token_accounts
        if item.get("mint") == USDC_MAINNET_MINT
    )
    return {
        "network": "solana-mainnet",
        "wallet": WALLET,
        "lamports": lamports,
        "sol": f"{lamports / 1_000_000_000:.9f}",
        "usdc_mint": USDC_MAINNET_MINT,
        "usdc_raw": str(usdc_raw),
        "usdc": f"{usdc_raw / 1_000_000:.6f}",
        "positive_token_accounts": token_accounts,
    }


def stable_view(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "network",
            "wallet",
            "lamports",
            "sol",
            "usdc_mint",
            "usdc_raw",
            "usdc",
            "positive_token_accounts",
        )
    }


def read_existing() -> dict[str, Any] | None:
    try:
        value = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def main() -> int:
    errors: list[str] = []
    snapshot: dict[str, Any] | None = None
    used_rpc: str | None = None
    for attempt, url in enumerate(RPC_URLS):
        try:
            snapshot = fetch_snapshot(url)
            used_rpc = url
            break
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            if attempt + 1 < len(RPC_URLS):
                time.sleep(2**attempt)
    if snapshot is None:
        raise ProbeError("; ".join(errors) or "No Solana RPC endpoint configured")

    previous = read_existing()
    changed = previous is None or stable_view(previous) != stable_view(snapshot)
    if changed:
        snapshot["first_observed_or_changed_at"] = now_iso()
        snapshot["rpc_url"] = used_rpc
        snapshot["evidence_boundary"] = (
            "This file proves the public on-chain balance observed by a Solana RPC. "
            "It does not identify the sender or prove that a transfer was caused by a specific task."
        )
        atomic_write(OUTPUT, snapshot)

    print(
        json.dumps(
            {
                "ok": True,
                "changed": changed,
                "wallet": WALLET,
                "sol": snapshot["sol"],
                "usdc": snapshot["usdc"],
                "positive_token_accounts": len(snapshot["positive_token_accounts"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
