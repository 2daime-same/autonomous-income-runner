# Autonomous Income Runner

A public, evidence-first workspace for paid engineering, MCP integration, API/CI quality assurance, and the autonomous-income experiment that funds it.

This repository is isolated from the owner's pre-existing development projects. Only work created for this mission is stored or modified here.

## Verified commercial status

Read [`CANONICAL_STATUS.md`](CANONICAL_STATUS.md) before interpreting any workflow, product, mission, or bounty output.

| Ledger item | Verified amount |
|---|---:|
| New income | JPY 0 |
| Receivable | JPY 0 |
| Spend | JPY 0 |
| Mission complete | No |

A listed reward, completed implementation, published product, proposal, pull request, demo, or optional tip request is **not revenue**. Only an externally verifiable payment, positive platform balance, or legally enforceable receivable changes this ledger.

## Verified deliverables

These are working technical assets with reproducible evidence. They are not claims of platform acceptance or payment.

| Deliverable | What is implemented | Verification | Source and evidence |
|---|---|---|---|
| **GitHub PR Review MCP** | TypeScript stdio MCP with 8 tools, PAT and GitHub App auth, inline-diff resolution, read/write credential separation, explicit write confirmation, pagination, rate-limit evidence, and opt-in review prompts | 20 tests; Node.js 20.11/22; 91.35% line coverage; live public-PR reads; one authorized inline-comment acceptance visible in 1,160 ms; clean npm install plus installed-package MCP exercise in 5.385 s; 151 s H.264 demo | [`deliverables/archimedes-msn-00015/`](deliverables/archimedes-msn-00015/) · [`SUBMISSION_READINESS.md`](deliverables/archimedes-msn-00015/SUBMISSION_READINESS.md) |
| **Archimedes Public-Data MCP** | Read-only TypeScript MCP for public asset and funded-bounty discovery, with fixed public GET paths, bounded requests, redacted errors, and no account or transaction capability | 19 tests; Node.js 20.11/22; 93.65% line coverage; four-tool public live smoke; production audit; CycloneDX SBOM | [`deliverables/archimedes-msn-00013/`](deliverables/archimedes-msn-00013/) · [`SUBMISSION_BUNDLE.md`](deliverables/archimedes-msn-00013/SUBMISSION_BUNDLE.md) |
| **Engineering Unit Conversion API** | FastAPI REST service for 8 engineering domains, 114 units, affine temperature handling, incompatible-quantity rejection, Docker deployment, OpenAPI, and local-only calculations | 79 tests; 96% coverage; real Uvicorn smoke; Docker build/start/health validation | [`deliverables/archimedes-msn-00014/`](deliverables/archimedes-msn-00014/) · [`SUBMISSION_BUNDLE.md`](deliverables/archimedes-msn-00014/SUBMISSION_BUNDLE.md) |

All material use of AI assistance, background technology, third-party dependencies, and open-source licenses is disclosed in the relevant submission packet.

## Paid engineering requests

A buyer can request a small, objectively testable engagement through the repository's **Paid engineering request** Issue Form. Opening a request is free and creates no payment obligation for either party.

Indicative starting scopes:

| Service | Typical evidence | Indicative budget |
|---|---|---:|
| Reproduce a public API or CI defect | Minimal reproduction, request/response matrix, root-cause boundary, acceptance test | USD 5–25 |
| MCP installation and integration verification | Clean-install log, configuration example, tool inventory, failure diagnosis | USD 25+ |
| Read-only MCP adapter for a documented public API | Source, schemas, tests, safety boundary, setup guide | USD 75+ |
| Guarded GitHub PR-review MCP customization | Scoped tools, permission model, write gates, tests, integration evidence | USD 150+ |
| Reproducible technical tutorial or implementation QA | Original text/code, runnable evidence, disclosure and source notes | By written agreement |

These amounts are non-binding estimates. Before work begins, both sides must agree in writing on scope, acceptance criteria, price, rights, deadline, payment method, and whether AI-assisted implementation is acceptable. For a very small public task, payment after accepted delivery can be proposed; larger or private work requires explicit milestone terms.

### Request rules

1. Use the **Paid engineering request** Issue Form.
2. Provide only public or sanitized context.
3. Never paste API keys, tokens, passwords, private keys, customer data, private source code, personal information, or confidential documents into an issue.
4. A request is accepted only after a written scope and price are agreed. Silence or exploratory discussion is not acceptance.
5. Test evidence is reported truthfully. Unrun tests, inaccessible hardware, and external-account limitations are stated explicitly.

## Evidence standard

Every completed engagement should include, where applicable:

- exact source revision and dependency lockfile;
- commands needed to reproduce the result;
- machine-readable test or request evidence;
- hashes for final archives and large artifacts;
- documented side effects and external writes;
- credential-leakage checks;
- explicit limitations and unresolved risks;
- AI-assistance and license disclosure.

## Automated opportunity system

The repository also contains read-only or tightly gated scanners for public paid-work channels. A candidate reaches implementation only when the canonical source is open, funding evidence and submission path are credible, competition is low, no fee or deposit is required, and the task does not request secrets or hidden prompts.

The strict selector rejects:

- system-prompt, runtime-instruction, startup-context, or private-context extraction;
- social spam, fake reviews, and fabricated identity or experience;
- upfront deposits, bonds, purchases, gas, or stakes;
- closed, deleted, missing, assigned, already rewarded, or heavily competed work;
- hardware or account dependencies that cannot be truthfully validated;
- ambiguous writes that would be unsafe to retry.

Current execution-grade public bounty inventory is zero. The official Algora SDK snapshot also currently returns zero active items. See [`market-output/`](market-output/) and [`reports/`](reports/) for evidence rather than relying on marketplace card text.

## Superteam agent integration

The original integration remains available for agent-eligible Superteam Earn work:

- `request.json` selects one operation;
- `runner.py` supports listing, details, comments, submission, update, and encrypted claim-state handling;
- plaintext API keys and claim codes are never committed;
- public-safe execution encrypts private state with the committed certificate and deletes plaintext before any commit;
- non-idempotent external writes are not automatically retried after ambiguous failures.

## Safety boundaries

- No fees, deposits, purchases, paid registrations, or financial transfers without explicit human approval.
- No fabricated identity, age, country, employment, qualifications, inventory, customer, or test result.
- No secrets or personal data in Git history, Issues, logs, artifacts, or public evidence.
- No modification of the owner's protected pre-existing repositories.
- Account creation, terms acceptance, age/country certification, KYC, tax/bank details, Stripe onboarding, npm account/2FA, IP assignment, and final legal submission remain human-controlled.
- No VPN, false location, nominee account, duplicate account, or other geographic circumvention.

## Contact

Use **Issues → New issue → Paid engineering request** with public or sanitized information. Do not send credentials or confidential material before a secure exchange and written scope have been agreed.
