#!/usr/bin/env python3
"""Record a compact, non-secret view of recent income workflow executions."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "2daime-same/autonomous-income-runner")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUTPUT = Path("ops-output/actions-status.json")
API = "https://api.github.com"
INCOME_NAMES = {
    "Resume autonomous income workers",
    "Run AgentJob paid campaign",
    "Run AgentJob paid-only worker v2",
    "Run BotHire paid-work provider",
    "Earn first Clawlancer micro-bounty",
    "Contain exposed Clawlancer credential",
    "Pause exposed Clawlancer agent",
    "Run AgentGigs paid-work worker",
    "Run TaskForce paid-work worker",
    "Run autonomous AgentGigs worker",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get(path: str) -> Any:
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "autonomous-income-runner-actions-probe/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"GitHub API HTTP {error.code}: {body}") from error


def compact_job(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "status": job.get("status"),
        "conclusion": job.get("conclusion"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "html_url": job.get("html_url"),
        "steps": [
            {
                "name": step.get("name"),
                "status": step.get("status"),
                "conclusion": step.get("conclusion"),
                "number": step.get("number"),
            }
            for step in (job.get("steps") or [])
            if isinstance(step, Mapping)
        ],
    }


def main() -> int:
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required")
    encoded_repo = urllib.parse.quote(REPOSITORY, safe="/")
    payload = get(f"/repos/{encoded_repo}/actions/runs?per_page=100")
    raw_runs = payload.get("workflow_runs") if isinstance(payload, Mapping) else []
    runs: list[dict[str, Any]] = []
    for run in raw_runs or []:
        if not isinstance(run, Mapping):
            continue
        name = str(run.get("name") or "")
        path = str(run.get("path") or "")
        if name not in INCOME_NAMES and not any(
            marker in (name + " " + path).lower()
            for marker in ("income", "bothire", "agentgigs", "agentjob", "clawlancer", "taskforce")
        ):
            continue
        run_id = run.get("id")
        jobs_payload = get(f"/repos/{encoded_repo}/actions/runs/{run_id}/jobs?per_page=100") if run_id else {}
        jobs = jobs_payload.get("jobs") if isinstance(jobs_payload, Mapping) else []
        runs.append(
            {
                "id": run_id,
                "name": name,
                "path": path,
                "event": run.get("event"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "run_number": run.get("run_number"),
                "run_attempt": run.get("run_attempt"),
                "head_sha": run.get("head_sha"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "html_url": run.get("html_url"),
                "jobs": [compact_job(job) for job in (jobs or []) if isinstance(job, Mapping)],
            }
        )
        if len(runs) >= 30:
            break

    report = {
        "generated_at": now_iso(),
        "repository": REPOSITORY,
        "income_workflow_run_count": len(runs),
        "runs": runs,
        "writes_performed": [],
        "credentials_recorded": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)
    print(json.dumps({"ok": True, "runs": len(runs), "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
