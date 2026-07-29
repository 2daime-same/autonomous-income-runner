# ClawGig integration

This directory contains the public, non-secret control plane for the mission's ClawGig agent.

- `request.json` selects an owner-triggered operation.
- `input/verify-code.cms.b64` carries only public-key-encrypted email verification material.
- `output/` contains sanitized evidence, a public transport certificate, and CMS-encrypted recovery state.
- `.clawgig-state/` is ignored by Git and persisted only in an owner-triggered GitHub Actions cache.

The workflow never runs on pull requests. It does not execute untrusted code, pay fees, fund escrow, hire agents, or withdraw funds. Proposals are submitted only after the nine ClawGig readiness checks pass and each requested gig is revalidated as open.
