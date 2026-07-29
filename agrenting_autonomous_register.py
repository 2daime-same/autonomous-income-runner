#!/usr/bin/env python3
"""Run the shared guarded autonomous-registration policy against Agrenting."""
from __future__ import annotations

import worq_autonomous_register as guard


guard.BASE = "https://agrenting.com"
guard.OPENAPI_URL = guard.BASE + "/openapi.json"
guard.SKILL_URL = guard.BASE + "/skill.md"
guard.PRIVATE_STATE = guard.Path(guard.os.environ.get("AGRENTING_PRIVATE_STATE", ".agrenting-state/state.json"))
guard.PUBLIC_OUTPUT = guard.Path(guard.os.environ.get("AGRENTING_PUBLIC_OUTPUT", "agrenting-output/result.json"))

if __name__ == "__main__":
    raise SystemExit(guard.main())
