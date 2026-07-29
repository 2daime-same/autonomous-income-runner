#!/usr/bin/env python3
"""Run the shared guarded autonomous-registration policy against AgentJob."""
from __future__ import annotations

import worq_autonomous_register as guard


guard.BASE = "https://agent-job.ai"
guard.OPENAPI_URL = guard.BASE + "/openapi.json"
guard.SKILL_URL = guard.BASE + "/skill.md"
guard.PRIVATE_STATE = guard.Path(guard.os.environ.get("AGENTJOB_PRIVATE_STATE", ".agentjob-state/state.json"))
guard.PUBLIC_OUTPUT = guard.Path(guard.os.environ.get("AGENTJOB_PUBLIC_OUTPUT", "agentjob-output/result.json"))

if __name__ == "__main__":
    raise SystemExit(guard.main())
