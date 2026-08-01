#!/usr/bin/env python3
"""Harden the strict bounty selector against prompt-exfiltration bounty farms.

This compatibility layer extends the base selector without duplicating its
ranking and evidence logic.  The base module deliberately has broad support for
known platforms; this layer adds repository- and phrase-level denials learned
from current live adversarial listings.

It is read-only with respect to external systems.  Running it only reads the
radar JSON and writes the sanitized local candidate projection selected by the
base module.
"""
from __future__ import annotations

import strict_candidate_selector as base


ADVERSARIAL_REPOSITORIES = {
    "unsafelabs/bounty-hunters",
    "securebananalabs/bug-bounty",
}

PROMPT_EXFILTRATION_EXTENSIONS = (
    "runtime instructions",
    "runtime_instructions",
    "initial directives",
    "initial_directives",
    "boot context",
    "boot_context",
    "session init",
    "session_init",
    "before any user messages",
    "before the user's first message",
    "before the first human message",
    "entire block of text present at the start",
    "complete block of text present at the start",
    "complete set of rules, instructions, and context",
    "complete set of rules, instructions",
    "everything that appeared in your context",
    "initialization text from the start of your session",
    "paste verbatim the entire block",
    "full startup context",
    "complete startup context",
    "complete startup rules",
    "hidden runtime instructions",
    "all instructions, guidelines, and configuration",
)

# The base safety function resolves these module globals at call time, so the
# extended policy applies both to direct calls and to base.main().
base.KNOWN_SYNTHETIC_REPOS = set(base.KNOWN_SYNTHETIC_REPOS) | ADVERSARIAL_REPOSITORIES
base.PROMPT_EXFILTRATION = tuple(
    dict.fromkeys((*base.PROMPT_EXFILTRATION, *PROMPT_EXFILTRATION_EXTENSIONS))
)

# Re-export the policy surface used by tests and future callers.
safety_flags = base.safety_flags
scope_score = base.scope_score
candidate_text = base.candidate_text
known_platform_evidence = base.known_platform_evidence


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
