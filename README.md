# Autonomous Income Runner

Isolated execution surface for agent-eligible paid-work APIs.

This repository belongs exclusively to the autonomous income mission. Existing development repositories are never used or modified.

## Current integration

The first connected marketplace is the official Superteam Earn agent API.

- `request.json` selects one API operation.
- `runner.py` registers an agent, lists agent-eligible work, fetches listing details and comments, posts clarification comments, and submits or updates completed work.
- `output/` contains sanitized evidence plus an encrypted copy of private registration state.
- `.github/workflows/agent-api.yml` runs only on an owner-controlled push or manual dispatch. It does not run on pull requests or on a recurring schedule.
- `keys/superteam-state-public.crt` is an encryption certificate only. It cannot decrypt the private state.

## Supported operations

- `list`
- `details`
- `comments`
- `comment_create`
- `submit`
- `update_submission`
- `reveal_claim` — disabled in public-safe execution; encrypted state must be decrypted privately after a verified win

The initial `request.json` uses `list` to register an agent and fetch currently live agent-eligible opportunities.

## Public-safe execution design

The repository is prepared to use free GitHub-hosted Actions without exposing platform credentials:

1. The workflow validates the request and runs the unit tests.
2. `runner.py` registers a short-lived agent and performs the requested operation with `PUBLIC_SAFE_MODE=1`.
3. The API key and claim code are written temporarily to `.agent-state/superteam.json`.
4. OpenSSL CMS encrypts that file to `output/private-state.cms` using the committed public certificate.
5. The plaintext state is deleted before any commit.
6. A recursive credential scan blocks the output commit if a secret appears in public JSON.
7. Only sanitized results, the ciphertext, and its checksum are committed.

The corresponding private key is stored outside GitHub in the mission's private Google Drive folder. Git history contains no private key.

Because each public-safe run is intentionally self-contained, it creates a new platform agent instead of restoring plaintext credentials from an unsafe public cache. This is acceptable for initial discovery and a small number of targeted submissions; it is not intended for high-volume automation.

## Safety boundaries

- No existing GitHub repository is modified.
- No fees, deposits, purchases, or paid registrations are permitted without explicit human approval.
- No fabricated identity, qualifications, inventory, test results, or human experience.
- API keys, claim codes, private keys, payment data, and personal information must never be committed.
- Non-idempotent writes are not automatically retried after ambiguous network failures.
- Pull requests cannot trigger external paid-work API calls.
- A human completes payout identity, profile, KYC, wallet, tax, or contract steps only after a verified earning event requires them.
