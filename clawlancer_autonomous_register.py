#!/usr/bin/env python3
"""Run the shared guarded autonomous-registration policy against Clawlancer."""
from __future__ import annotations

import worq_autonomous_register as guard


guard.BASE = "https://clawlancer.ai"
guard.OPENAPI_URL = guard.BASE + "/openapi.json"
guard.SKILL_URL = guard.BASE + "/api/info"
guard.PRIVATE_STATE = guard.Path(guard.os.environ.get("CLAWLANCER_PRIVATE_STATE", ".clawlancer-state/state.json"))
guard.PUBLIC_OUTPUT = guard.Path(guard.os.environ.get("CLAWLANCER_PUBLIC_OUTPUT", "clawlancer-output/result.json"))

if __name__ == "__main__":
    raise SystemExit(guard.main())
