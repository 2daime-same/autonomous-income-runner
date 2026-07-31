# Submission brief — Archimedes MSN-00013

## Candidate deliverable

- Mission: `MSN-00013`
- Public title: `Develop an MCP Server for Archimedes Market`
- Implementation: unofficial TypeScript stdio MCP server
- License: MIT
- Capability boundary: unauthenticated public reads only
- Submission status: **not submitted**
- Acceptance status: **not accepted**
- Verified revenue or receivable: **0**

The public bounty snapshot displayed a funded/locked reward, but a displayed amount is not income or a receivable.

## Delivered features

- `search_assets`
- `get_asset`
- `search_bounties`
- `get_bounty`
- strict TypeScript configuration
- read-only MCP annotations
- public HTTP client with timeout, response-size, rate-limit, retry, URL, and identifier controls
- safe structured errors
- unit tests
- real stdio MCP integration test
- controlled live acceptance smoke script
- setup, integration, architecture, security, and requirement-conflict documentation
- deterministic CI packaging and SHA-256 manifest

## Reproduction

```bash
npm install
npm run verify
npm run live:smoke
```

The live smoke is read-only. It does not create an account, accept terms, apply, claim, submit, buy, upload, or configure Stripe.

## Acceptance traceability

| Acceptance item | Verification |
|---|---|
| Server starts and registers tools | stdio MCP integration test |
| `search_assets` works with “Python” | mock-backed integration plus controlled live smoke |
| `get_asset` returns a public asset | mock-backed integration plus controlled live smoke |
| `search_bounties` returns public missions | mock-backed integration plus controlled live smoke |
| `get_bounty` returns mission detail | mock-backed integration plus controlled live smoke |
| Package starts with npm | build + `npm start`; CI package dry run |
| Documentation included | README, architecture, security, conflict note, this brief |

## Known requirement ambiguity

The mission snapshot contains both Python/TensorFlow/Flask/AWS requirements and TypeScript/MCP/npm requirements. This implementation follows the TypeScript deliverable and the four automated acceptance tools. See `docs/REQUIREMENTS-CONFLICT.md`. Official clarification is required before representing the legacy Python/cloud language as waived.

## Human-controlled boundary

Account registration, residency statements, terms acceptance, identity verification, Stripe or bank onboarding, final submission, and any legal warranty remain actions for the human account owner after platform eligibility and requirement interpretation are confirmed.
