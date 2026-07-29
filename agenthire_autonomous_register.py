#!/usr/bin/env python3
"""Run the shared guarded autonomous-registration policy against AgentHire."""
from __future__ import annotations

import worq_autonomous_register as guard


guard.BASE = "https://api.agenthire.app"
guard.OPENAPI_URL = guard.BASE + "/openapi.json"
guard.SKILL_URL = "https://www.agenthire.app/skill.md"
guard.PRIVATE_STATE = guard.Path(
    guard.os.environ.get("AGENTHIRE_PRIVATE_STATE", ".agenthire-state/state.json")
)
guard.PUBLIC_OUTPUT = guard.Path(
    guard.os.environ.get("AGENTHIRE_PUBLIC_OUTPUT", "agenthire-output/result.json")
)


if __name__ == "__main__":
    raise SystemExit(guard.main())
