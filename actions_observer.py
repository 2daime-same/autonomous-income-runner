#!/usr/bin/env python3
"""Observe selected autonomous-income-runner Actions without exposing secrets."""
from __future__ import annotations

import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API = "https://api.github.com"
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "nexaworks-jp/autonomous-income-runner")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUTPUT = Path(os.environ.get("ACTIONS_OBSERVER_OUTPUT", "ops-output/fkill-actions.json"))
TARGET_NAMES = {
    "Validate fkill IssueHunt bounty 25",
    "Diagnose fkill bounty patch",
    "Run encrypted AgentJob live worker",
    "Run paid-only AgentJob worker v2",
    "Probe GitHub Models inference",
    "Test workflow secret persistence capability",
    "Try multiple Clawlancer micro-bounties",
    "Probe AgentQ task and payout contract",
    "Run TaskForce paid-work worker",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request(path: str, *, accept: str = "application/vnd.github+json") -> bytes:
    headers = {
        "Accept": accept,
        "User-Agent": "autonomous-income-runner-actions-observer/1.3",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {error.code} for {path}: {detail}") from error


def request_json(path: str) -> Any:
    raw = request(path)
    return json.loads(raw.decode("utf-8")) if raw else None


def sanitize_log(text: str) -> str:
    patterns = (
        (r"gh[opsu]_[A-Za-z0-9_]+", "[REDACTED_GITHUB_TOKEN]"),
        (r"cph_[A-Za-z0-9_-]+", "[REDACTED_CLAWHUNT_TOKEN]"),
        (r"\b(?:ak|aj|agentjob)_[A-Za-z0-9_-]{8,}", "[REDACTED_AGENTJOB_KEY]"),
        (r"\bapv_[A-Za-z0-9._~+/=-]{8,}", "[REDACTED_TASKFORCE_KEY]"),
        (r"\b(?:claw|cl|api|sk)_[A-Za-z0-9_-]{12,}", "[REDACTED_API_KEY]"),
        (r"Authorization:\s*(?:Bearer|Basic)\s+\S+", "Authorization: [REDACTED]"),
        (r"https://[^\s\"']*(?:alchemy\.com|infura\.io)/(?:v2|v3)/[^\s\"']+", "https://[REDACTED_PROVIDER_ENDPOINT]"),
        (r"\b0x[0-9a-fA-F]{64}\b", "[REDACTED_PRIVATE_KEY]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def job_log_tail(job_id: int, lines: int = 180) -> str | None:
    try:
        raw = request(f"/repos/{REPOSITORY}/actions/jobs/{job_id}/logs")
    except Exception as error:
        return f"log fetch failed: {type(error).__name__}: {error}"

    text: str
    if raw.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                chunks = []
                for name in archive.namelist():
                    if name.endswith("/"):
                        continue
                    chunks.append(archive.read(name).decode("utf-8", errors="replace"))
                text = "\n".join(chunks)
        except zipfile.BadZipFile:
            text = raw.decode("utf-8", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return "\n".join(sanitize_log(text).splitlines()[-lines:])


def main() -> int:
    data = request_json(f"/repos/{REPOSITORY}/actions/runs?per_page=100")
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    selected = [run for run in runs if run.get("name") in TARGET_NAMES][:30]
    output_runs = []
    for run in selected:
        run_id = int(run["id"])
        jobs_data = request_json(
            f"/repos/{REPOSITORY}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
        )
        jobs = jobs_data.get("jobs", []) if isinstance(jobs_data, dict) else []
        compact_jobs = []
        for job in jobs:
            conclusion = job.get("conclusion")
            compact = {
                "id": job.get("id"),
                "name": job.get("name"),
                "status": job.get("status"),
                "conclusion": conclusion,
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "steps": [
                    {
                        "name": step.get("name"),
                        "status": step.get("status"),
                        "conclusion": step.get("conclusion"),
                        "number": step.get("number"),
                    }
                    for step in (job.get("steps") or [])
                ],
            }
            if conclusion == "failure" and job.get("id"):
                compact["log_tail"] = job_log_tail(int(job["id"]))
            compact_jobs.append(compact)
        output_runs.append(
            {
                "id": run_id,
                "name": run.get("name"),
                "event": run.get("event"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "head_sha": run.get("head_sha"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "html_url": run.get("html_url"),
                "jobs": compact_jobs,
            }
        )

    result = {
        "generated_at": now_iso(),
        "repository": REPOSITORY,
        "target_workflows": sorted(TARGET_NAMES),
        "runs": output_runs,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "runs": len(output_runs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
