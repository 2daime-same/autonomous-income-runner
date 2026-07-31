# Submission brief — Archimedes MSN-00013

## Candidate deliverable

- Mission: `MSN-00013`
- Public title: `Develop an MCP Server for Archimedes Market`
- Implementation: unofficial TypeScript stdio MCP server
- License: MIT
- Capability boundary: unauthenticated public reads only
- Platform submission status: **not submitted**
- Acceptance status: **not accepted**
- Verified revenue or receivable: **0**

A publicly displayed funded/locked reward is an opportunity signal, not income or a receivable.

## Delivered features

- `search_assets`
- `get_asset`
- `search_bounties`
- `get_bounty`
- strict TypeScript and exact dependency lockfile
- read-only MCP annotations
- public asset discovery through same-origin sitemap UUIDs and static Product JSON-LD
- public bounty discovery through the unauthenticated bounty JSON API
- GET-only transport with timeout, size, retry, rate-limit, URL, identifier, catalog, and concurrency controls
- static HTML parsing without rendering or JavaScript execution
- stable structured results and redacted errors
- unit, parser, HTTP, and real stdio MCP integration tests
- controlled live four-tool acceptance smoke test
- setup, integration, architecture, security, and requirement-conflict documentation
- deterministic CI packaging, SHA-256 manifest, dependency audit, and CycloneDX SBOM

## Reproduction

```bash
npm ci
npm run verify
npm run live:smoke
npm run package:submission
```

The live smoke is read-only. It does not create an account, accept terms, apply, claim, submit, buy, upload, or configure Stripe.

## Acceptance traceability

| Acceptance item | Verification |
|---|---|
| Server starts and registers exactly four tools | real stdio MCP integration test |
| `search_assets` works with `Python` | parser/client tests plus controlled live smoke |
| `get_asset` returns a public asset | Product JSON-LD binding tests plus controlled live smoke |
| `search_bounties` returns public missions | mock-backed tests plus controlled live smoke |
| `get_bounty` returns mission detail | mock-backed tests plus controlled live smoke |
| Works on minimum supported runtime | Node.js 20.11 CI job |
| npm package is complete | exact lockfile, build, `npm pack --dry-run`, manifest |
| Supply-chain evidence exists | critical production audit and CycloneDX SBOM |
| Submission ZIP is reproducible and intact | fixed timestamps, file manifest, generated SHA-256, checksum verification |
| Documentation is complete | README, architecture, security, conflict note, this brief |

The authoritative test count, coverage output, live resource IDs, commit, archive hash, SBOM, and audit result are generated in the GitHub Actions artifact. They are intentionally not copied into this source file because changing the source would itself change the final archive hash.

## Known requirement ambiguity

The mission snapshot contains both Python/TensorFlow/Flask/cloud requirements and TypeScript/MCP/npm requirements. This implementation follows the objective TypeScript deliverable and the four automated acceptance tools. See `docs/REQUIREMENTS-CONFLICT.md`. Official clarification is required before representing the legacy Python/cloud language as waived.

## Human-controlled boundary

Account registration, age or residency statements, terms acceptance, identity verification, Stripe or bank onboarding, final upload/submission, and any legal warranty remain actions for the human account owner after platform eligibility and requirement interpretation are confirmed.
