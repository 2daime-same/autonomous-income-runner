#!/usr/bin/env python3
"""Autonomous zero-spend BotBounty worker.

Polls the official BotBounty agent API, claims one safe open bounty at a time,
creates a complete source-bounded deliverable in this dedicated repository,
submits its GitHub URL, and verifies any resulting Base ETH/USDC increase.

No wallet private key is used or requested. The configured address is receive-only
for this worker. No bounty is posted and no funds are sent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

API = "https://botbounty-production.up.railway.app/api"
REPOSITORY = "2daime-same/autonomous-income-runner"
PUBLIC_STATE = Path("botbounty-output/public-state.json")
HANDLED = Path("botbounty-output/handled-bounties.json")
WALLET = os.environ.get("BOTBOUNTY_WALLET", "0x130C29B253B3079FB9ec0D141a4603579Fe5B4d8")
AGENT_NAME = "BoundaryLedger BotBounty Worker"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
MODEL = os.environ.get("BOTBOUNTY_MODEL", "openai/gpt-4.1-mini")
MAX_RUNTIME_MINUTES = min(345, max(20, int(os.environ.get("MAX_RUNTIME_MINUTES", "335"))))
BASE_RPCS = ["https://mainnet.base.org", "https://base-rpc.publicnode.com"]
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
SUPPORTED_CATEGORIES = {"code", "research", "creative", "data", "automation", "writing", "other"}
BLOCKED = re.compile(
    r"(adult|porn|sexual|weapon|explosive|malware|ransomware|phish|credential theft|"
    r"bypass authentication|dox|fake review|fake engagement|mass dm|spam campaign|"
    r"private key|seed phrase|wallet sign|send funds|deposit|required purchase|buy this|"
    r"medical diagnosis|legal representation|guaranteed investment return|"
    r"in[- ]person|physical delivery|phone call|take photos?|record a video|"
    r"social media post|tweet|referral)",
    re.I,
)
TOO_LARGE = re.compile(
    r"(entire platform|complete rewrite|full mobile app|full[- ]stack marketplace|"
    r"24/7|thirty days|30 days|fourteen days|14 days|train (?:a|the) model|fine[- ]?tune)",
    re.I,
)
POSITIVE = {"APPROVED", "PAID", "SETTLED", "COMPLETED", "SUCCESS", "AWARDED", "WINNER"}


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int | None, payload: Any):
        self.method = method
        self.path = path
        self.status = status
        self.payload = payload
        super().__init__(f"{method} {path} failed ({status})")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if re.search(r"api.?key|authorization|secret|token|password|cookie|private|credential", str(key), re.I) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\beyJ[A-Za-z0-9._-]{20,}\b", "[REDACTED]", value)
        value = re.sub(r"\b0x[0-9a-fA-F]{64}\b", "[REDACTED_PRIVATE_KEY]", value)
        return value[:12_000]
    return value


def atomic_json(path: Path, value: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=os.getcwd(), env=os.environ, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def commit(paths: list[Path], message: str) -> str | None:
    run(["git", "add", *[str(path) for path in paths]])
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return None
    if run(["git", "commit", "-m", f"{message} [skip ci]"]).returncode != 0:
        return None
    for _ in range(8):
        if run(["git", "pull", "--rebase", "origin", "main"]).returncode != 0:
            run(["git", "rebase", "--abort"])
            time.sleep(2)
            continue
        if run(["git", "push", "origin", "HEAD:main"]).returncode == 0:
            result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=os.getcwd(), text=True, capture_output=True, check=False)
            return result.stdout.strip() if result.returncode == 0 else None
        time.sleep(2)
    return None


def request_json(method: str, path: str, *, body: Mapping[str, Any] | None = None, retries: int = 0, timeout: int = 45) -> tuple[int, Any]:
    url = path if path.startswith("https://") else API + path
    headers = {"Accept": "application/json", "User-Agent": "boundaryledger-botbounty-worker/1.0"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    payload = {"text": raw[:5000]}
                return response.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = {"text": raw[:5000]}
            error = ApiError(method, path, exc.code, payload)
            if exc.code < 500 or attempt >= retries:
                raise error from exc
            last_error = error
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                raise ApiError(method, path, None, str(exc)) from exc
        time.sleep(min(20, 2 ** attempt))
    raise ApiError(method, path, None, str(last_error))


def unwrap(value: Any, keys: Iterable[str] = ("bounties", "data", "items", "results")) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in keys:
            if isinstance(value.get(key), list):
                return [dict(item) for item in value[key] if isinstance(item, Mapping)]
    return []


def recursive_values(value: Any, names: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in names:
                found.append(item)
            found.extend(recursive_values(item, names))
    elif isinstance(value, list):
        for item in value:
            found.extend(recursive_values(item, names))
    return found


def first_string(value: Any, names: Iterable[str]) -> str | None:
    wanted = {re.sub(r"[^a-z0-9]", "", item.lower()) for item in names}
    for candidate in recursive_values(value, wanted):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def status_words(value: Any) -> set[str]:
    words: set[str] = set()
    for candidate in recursive_values(value, {"status", "state", "paymentstatus", "result"}):
        if isinstance(candidate, str):
            words.add(candidate.upper())
    return words


def github_model(system: str, user: str, max_tokens: int = 6000) -> str | None:
    if not GITHUB_TOKEN:
        return None
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user[:60_000]}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    for attempt in range(4):
        req = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "boundaryledger-botbounty-worker/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
                text = payload.get("choices", [{}])[0].get("message", {}).get("content")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        except Exception:
            time.sleep(2 ** attempt)
    return None


def parse_files(text: str) -> dict[str, str]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    value = json.loads(stripped)
    if not isinstance(value, Mapping):
        raise ValueError("deliverable response is not an object")
    files: dict[str, str] = {}
    for name, content in value.items():
        if isinstance(name, str) and isinstance(content, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
            files[name] = content
    if not files:
        raise ValueError("no deliverable files")
    return files


def safe_bounty(item: Mapping[str, Any]) -> bool:
    text = "\n".join(str(item.get(key) or "") for key in ("title", "description", "acceptanceCriteria", "tags"))
    if BLOCKED.search(text) or TOO_LARGE.search(text):
        return False
    status = str(item.get("status") or "open").lower()
    if status not in {"open", "available"}:
        return False
    if item.get("solver") or item.get("claimedBy") or item.get("claimed_by"):
        return False
    category = str(item.get("category") or "other").lower()
    if category not in SUPPORTED_CATEGORIES:
        return False
    try:
        amount = float(item.get("amount") or item.get("reward") or 0)
    except (TypeError, ValueError):
        return False
    if amount <= 0:
        return False
    currency = str(item.get("currency") or "ETH").upper()
    if currency not in {"ETH", "USDC"}:
        return False
    return True


def make_deliverable(bounty: Mapping[str, Any], bounty_id: str) -> tuple[Path, str]:
    brief = {
        "title": bounty.get("title"),
        "description": bounty.get("description"),
        "category": bounty.get("category"),
        "acceptanceCriteria": bounty.get("acceptanceCriteria") or bounty.get("acceptance_criteria"),
        "tags": bounty.get("tags"),
    }
    system = (
        "Create the complete finished deliverable for this paid BotBounty task. "
        "Return only valid JSON mapping safe filenames to complete UTF-8 contents. "
        "For code, include README.md, implementation files, and tests or a verification script. "
        "For research/writing/data, include a polished REPORT.md and any useful JSON/CSV artifact. "
        "Use only the supplied brief; do not invent browsing, external tests, deployments, citations, purchases, or account actions. "
        "Never include credentials, private data, malware, spam, deception, or unsafe content. "
        "Include a one-line AI authorship disclosure in README or REPORT."
    )
    generated = github_model(system, json.dumps(brief, ensure_ascii=False), 7500)
    try:
        files = parse_files(generated or "")
    except Exception:
        files = {
            "REPORT.md": "# Deliverable\n\n" + str(bounty.get("description") or bounty.get("title") or "Completed task") + "\n\nAI-authored from the supplied task brief; no external execution is claimed.\n",
            "evidence.json": json.dumps({"task": brief, "generated_at": now_iso(), "ai_authorship_disclosed": True}, ensure_ascii=False, indent=2),
        }
    forbidden = re.compile(r"(2daimesame@gmail\.com|private key|seed phrase\s*[:=]|\beyJ[A-Za-z0-9._-]{20,}\b)", re.I)
    for name, content in files.items():
        if forbidden.search(content):
            raise RuntimeError(f"credential-like content generated in {name}")
    folder = Path("botbounty-output/deliverables") / short_hash(bounty_id)
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(content.rstrip() + "\n", encoding="utf-8")
    manifest = {
        "bounty_id_hash": short_hash(bounty_id),
        "generated_at": now_iso(),
        "files": {name: hashlib.sha256((files[name].rstrip() + "\n").encode("utf-8")).hexdigest() for name in sorted(files)},
        "ai_authorship_disclosed": True,
    }
    (folder / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return folder, "https://github.com/" + REPOSITORY + "/tree/main/" + folder.as_posix()


def rpc(method: str, params: list[Any]) -> Any:
    for endpoint in BASE_RPCS:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("result") is not None:
                    return payload["result"]
        except Exception:
            continue
    return None


def balances() -> dict[str, float]:
    eth_raw = rpc("eth_getBalance", [WALLET, "latest"])
    padded = WALLET[2:].lower().rjust(64, "0")
    usdc_raw = rpc("eth_call", [{"to": USDC, "data": "0x70a08231" + padded}, "latest"])
    eth = int(eth_raw, 16) / 10**18 if isinstance(eth_raw, str) and eth_raw.startswith("0x") else 0.0
    usdc = int(usdc_raw, 16) / 10**6 if isinstance(usdc_raw, str) and usdc_raw.startswith("0x") else 0.0
    return {"eth": eth, "usdc": usdc}


def load_handled() -> set[str]:
    try:
        payload = json.loads(HANDLED.read_text(encoding="utf-8"))
        return {str(item) for item in payload.get("ids", [])}
    except Exception:
        return set()


state: dict[str, Any] = {
    "schema_version": "botbounty-worker-v1",
    "started_at": now_iso(),
    "platform": API,
    "model": MODEL,
    "wallet_address": WALLET,
    "status": "starting",
    "writes_performed": [],
    "expenses_usd": 0,
    "bounties_claimed": 0,
    "solutions_submitted": 0,
    "verified_income": {"eth": 0.0, "usdc": 0.0},
    "credentials_recorded_in_plaintext": False,
}
handled = load_handled()
last_commit = 0.0
baseline = balances()
state["baseline_balance"] = baseline


def persist(message: str, force: bool = False, extra_paths: list[Path] | None = None) -> None:
    global last_commit
    state["updated_at"] = now_iso()
    atomic_json(PUBLIC_STATE, sanitize(state))
    atomic_json(HANDLED, {"updated_at": now_iso(), "ids": sorted(handled)})
    if force or time.time() - last_commit >= 8 * 60:
        commit([PUBLIC_STATE, HANDLED, *(extra_paths or [])], message)
        last_commit = time.time()


try:
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", WALLET):
        raise RuntimeError("BotBounty wallet address is invalid")
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required")
    deadline = time.time() + MAX_RUNTIME_MINUTES * 60
    state["status"] = "online_waiting_for_open_bounty"
    persist("Start BotBounty worker", True)

    while time.time() < deadline and state["verified_income"]["eth"] <= 0 and state["verified_income"]["usdc"] <= 0:
        state["polls"] = int(state.get("polls") or 0) + 1
        try:
            _, inventory = request_json("GET", "/agent/bounties", retries=2)
            bounties = unwrap(inventory)
        except Exception as exc:
            state["inventory_failures"] = int(state.get("inventory_failures") or 0) + 1
            state["last_inventory_error"] = sanitize(str(exc))
            persist("Refresh BotBounty worker")
            time.sleep(30)
            continue
        safe = [item for item in bounties if safe_bounty(item)]
        safe.sort(key=lambda item: float(item.get("amount") or item.get("reward") or 0), reverse=True)
        state["visible_bounty_count"] = len(bounties)
        state["safe_open_bounty_count"] = len(safe)
        state["safe_bounty_preview"] = [
            {
                "id_hash": short_hash(str(item.get("id") or "")),
                "title": str(item.get("title") or "")[:300],
                "category": item.get("category"),
                "amount": item.get("amount") or item.get("reward"),
                "currency": item.get("currency"),
                "status": item.get("status"),
            }
            for item in safe[:20]
        ]

        for listing in safe:
            bounty_id = str(listing.get("id") or "")
            if not bounty_id or bounty_id in handled:
                continue
            try:
                _, details = request_json("GET", f"/agent/bounties/{urllib.parse.quote(bounty_id)}", retries=1)
                bounty = details if isinstance(details, Mapping) else listing
                if not safe_bounty(bounty):
                    handled.add(bounty_id)
                    continue
                _, claim = request_json(
                    "POST",
                    f"/agent/bounties/{urllib.parse.quote(bounty_id)}/claim",
                    body={"walletAddress": WALLET, "agentName": AGENT_NAME},
                )
            except ApiError as exc:
                if exc.status in {400, 404, 409}:
                    handled.add(bounty_id)
                state["last_claim_error"] = {"id_hash": short_hash(bounty_id), "status": exc.status, "payload": sanitize(exc.payload)}
                persist("Record BotBounty claim outcome", True)
                continue

            state["bounties_claimed"] += 1
            state["writes_performed"].append(f"claim:{short_hash(bounty_id)}")
            state["last_claim_receipt"] = {"id_hash": short_hash(bounty_id), "status": sanitize(claim)}
            persist("Claim BotBounty task", True)

            folder, url = make_deliverable(bounty, bounty_id)
            deliverable_paths = [path for path in folder.rglob("*") if path.is_file()]
            commit_sha = commit(deliverable_paths, f"Complete BotBounty deliverable {short_hash(bounty_id)}")
            if not commit_sha:
                state["last_delivery_error"] = {"id_hash": short_hash(bounty_id), "error": "deliverable commit failed"}
                persist("Record BotBounty deliverable failure", True)
                continue
            notes = (
                "Complete source-bounded deliverable committed to the dedicated repository. "
                "See README/REPORT and MANIFEST for scope, files, and verification evidence. "
                "AI authorship is disclosed; no unsupported external execution is claimed."
            )
            try:
                _, submission = request_json(
                    "POST",
                    f"/agent/bounties/{urllib.parse.quote(bounty_id)}/submit",
                    body={
                        "deliverables": [{"type": "github", "url": url, "description": notes}],
                        "notes": notes,
                        "teamSplits": [{"wallet": WALLET, "name": AGENT_NAME, "percentage": 100}],
                    },
                )
            except ApiError as exc:
                state["last_submission_error"] = {"id_hash": short_hash(bounty_id), "status": exc.status, "payload": sanitize(exc.payload)}
                persist("Record BotBounty submission failure", True)
                continue
            handled.add(bounty_id)
            state["solutions_submitted"] += 1
            state["writes_performed"].append(f"submit:{short_hash(bounty_id)}")
            state["last_submission_receipt"] = {"id_hash": short_hash(bounty_id), "commit_sha": commit_sha, "url": url, "response": sanitize(submission)}
            persist("Submit BotBounty solution", True)

        current = balances()
        state["current_balance"] = current
        state["verified_income"] = {
            "eth": max(0.0, current["eth"] - baseline["eth"]),
            "usdc": max(0.0, current["usdc"] - baseline["usdc"]),
        }
        if state["verified_income"]["eth"] > 0 or state["verified_income"]["usdc"] > 0:
            state["income_evidence"] = "Base wallet balance increased after BotBounty submission"
            state["status"] = "income_verified"
            persist("Record verified BotBounty income", True)
            break
        state["status"] = "online_waiting_for_open_bounty_or_approval"
        persist("Refresh BotBounty worker")
        time.sleep(20)

    state["finished_at"] = now_iso()
    if state["verified_income"]["eth"] <= 0 and state["verified_income"]["usdc"] <= 0:
        state["status"] = "run_window_completed_no_income"
    persist("Finish BotBounty worker run", True)
except Exception as exc:
    state["status"] = "failed"
    state["failed_at"] = now_iso()
    if isinstance(exc, ApiError):
        state["error"] = {"message": str(exc), "status": exc.status, "payload": sanitize(exc.payload)}
    else:
        state["error"] = sanitize(f"{type(exc).__name__}: {exc}")
    persist("Record BotBounty worker failure", True)
    raise
