# Autonomous Income Runner

Private, isolated execution surface for agent-eligible paid-work APIs.

This repository belongs exclusively to the autonomous income mission. Existing development repositories are never used or modified.

## Current integration

The first connected marketplace is the official Superteam Earn agent API.

- `request.json` selects one API operation.
- `runner.py` registers an agent, lists agent-eligible work, fetches listing details and comments, posts clarification comments, submits or updates completed work, and reveals the human claim code only after a verified win.
- `.agent-state/` is excluded from Git history. GitHub Actions persists credentials in this private repository's cache.
- `output/` contains sanitized evidence only.
- `.github/workflows/agent-api.yml` runs immediately on operational changes and refreshes listings every six hours.

## Supported operations

- `list`
- `details`
- `comments`
- `comment_create`
- `submit`
- `update_submission`
- `reveal_claim`

The initial `request.json` uses `list` to register the agent and fetch currently live agent-eligible opportunities.

## Safety boundaries

- No existing GitHub repository is modified.
- No fees, deposits, purchases, or paid registrations are permitted without explicit human approval.
- No fabricated identity, qualifications, inventory, test results, or human experience.
- API keys and claim codes are not committed during normal operation.
- Non-idempotent writes are not automatically retried after ambiguous network failures.
- A human completes payout identity, profile, KYC, wallet, tax, or contract steps only after a verified earning event requires them.
