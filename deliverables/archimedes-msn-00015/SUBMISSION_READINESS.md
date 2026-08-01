# MSN-00015 Submission Readiness Dossier

Status date: 2026-08-02 (Asia/Tokyo)

## Commercial status

- Verified income: **$0 / ¥0**
- Verified receivable: **$0 / ¥0**
- Expense: **$0 / ¥0**
- Archimedes submission performed: **No**
- npm publication performed: **No**

The bounty amount, completed implementation, CI artifacts, and an available npm name are not income or a receivable.

## Current official mission state

The public Archimedes MCP returned the following current record:

- Display ID: `MSN-00015`
- Mission UUID: `7176ab9f-1d21-4c98-b8b3-01d2cc3c273b`
- Title: `Build an MCP Server that Lets Claude Triage and Review GitHub PRs`
- Status: `open`
- Funding: funded; payment hold status `locked`
- Listed bounty: `$450.00`
- Deadline: `2026-08-21T23:59:59Z`
- Required deliverables: source repository, npm package, demo video

Public inventory evidence is stored at:

- `../../../market-output/archimedes-open-summary.json`

## Implementation evidence

- Package: `archimedes-github-pr-mcp`
- Candidate version: `1.0.0`
- License: MIT
- Runtime: Node.js `>=20.11`
- Transport: local stdio MCP
- Registered tools: 8
- Opt-in review prompts: 2
- Authentication: separate PAT read/write credentials and GitHub App installation tokens
- Write controls: process-level write enablement plus per-call `confirm=true`
- Reliability controls: bounded pagination, bounded response sizes, rate-limit reporting, same-origin GET redirects only, and no automatic POST retry

Final integrated source commit before the demo work:

- `9c008baff7913b76786e48a29ca2cdd41f413645`

Final verification run before the demo work:

- GitHub Actions run `30705769089`
- Node.js 20.11 and 22 verification
- 20 tests passed
- Line coverage: 91.35%
- Branch coverage: 75.41%
- Function coverage: 91.53%
- Production dependency vulnerabilities: 0
- Live public-PR read smoke test: passed
- Reproducible submission package and SBOM: generated

Canonical submission ZIP SHA-256:

- `bf1148280b23b5d256f79e9abbd8a9c056e6d887416341092672fd80537a62c1`

## Manual live-write acceptance

A temporary same-repository pull request was used only for the explicitly authorized write acceptance test.

- PR: `#7` (closed without merge)
- Workflow run: `30706913841`
- MCP write operation: exactly one inline review comment
- GitHub request duration: 562 ms
- Same comment visible through `list_pr_comments`: 1,160 ms
- Required visibility threshold: under 5 seconds
- Credential-pattern scan: passed
- Acceptance evidence artifact SHA-256: `571567b360c61c8a66f8a2581bba3e870f2bd4d5853cc2b7c3276d7666f756f0`

## Clean-install and demo evidence

The demo workflow performs these steps on a fresh `ubuntu-24.04` runner:

1. Installs locked dependencies.
2. Runs type checks, all tests, build, package inspection, and production audit.
3. Creates the npm tarball.
4. Installs that tarball into an empty npm project.
5. Starts the installed package rather than importing unpublished source.
6. Completes the MCP handshake and verifies all tools and prompts.
7. Uses the installed MCP package to read PR #7 from GitHub.
8. Verifies that the prior acceptance inline comment remains visible.
9. Demonstrates that a write call is rejected when writes are disabled and `confirm=false`.
10. Renders a narrated 1920×1080 H.264 demo from the generated evidence.

The resulting video, tarball, logs, hashes, and machine-readable evidence are uploaded as a GitHub Actions artifact. The lightweight artifact manifest is persisted under `demo-evidence/` after a successful run.

## npm registry state

The unauthenticated public npm registry check at `2026-08-01T18:24:15Z` found:

- Package name: `archimedes-github-pr-mcp`
- Existing package: no
- Available at check time: yes
- Publication attempted: no

Evidence:

- `demo-evidence/npm-name-status.json`

Name availability can change before publication and must be checked again immediately before the authorized publish operation.

## Remaining external actions

These actions cannot be truthfully completed by the repository workflow alone:

1. Create or use an npm account, accept npm's terms, complete any email/2FA requirements, and authorize publication.
2. Publish `archimedes-github-pr-mcp@1.0.0` to the public npm registry with provenance if available.
3. Create or use one truthful Archimedes account, accept the current terms, provide the actual country of residence, and complete required onboarding.
4. Confirm that access and Stripe Connect onboarding are available for the account's true jurisdiction.
5. Open the MSN-00015 Submission Workspace, attach the required deliverables, review the IP assignment and open-source disclosures, and perform the final submission.

No VPN, false country, nominee account, duplicate account, or other geographic circumvention may be used.

## Submission decision gate

Proceed to the account-level steps only when all of the following remain true:

- Mission status is still `open`.
- Funding/payment-hold state is still `locked`.
- The package name remains available or an approved replacement name is selected.
- The clean-install demo workflow is successful.
- The generated video and tarball hashes are fixed.
- The account can truthfully register from its actual country.
- Stripe Connect supports the actual account and bank jurisdiction.
- The user personally accepts the governing terms and final IP/submission action.

Until those conditions are satisfied, this dossier records technical readiness only; it does not claim acceptance, award, payout, or revenue.
