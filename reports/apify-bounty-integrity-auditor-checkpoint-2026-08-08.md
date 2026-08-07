# Apify bounty-integrity Actor checkpoint — 2026-08-08 JST

## Commercial ledger

- Confirmed new revenue: JPY 0 / USD 0
- Confirmed receivable: JPY 0 / USD 0
- Confirmed spend: JPY 0 / USD 0
- Apify Store publication: not yet performed
- Actor runs, customers, sales, and payouts: 0

## New revenue asset

A production-oriented Apify Actor was implemented under `products/apify-bounty-integrity-auditor/`.

The Actor accepts public GitHub issue URLs and checks canonical issue and comment evidence before a developer or coding agent spends time on a purported paid task. It detects:

- open/closed state and public reward evidence;
- IssueHunt, Algora, and Opire provider signals;
- already-referenced or submitted pull requests;
- maintainer hold-offs and duplicate-work warnings;
- requests for hidden prompts, credentials, private keys, private payout data, or artificial engagement;
- a deterministic verdict, blockers, evidence, confidence, and score.

It performs read-only GitHub API access. It does not execute issue text, clone or run third-party code, post comments, claim work, submit pull requests, or expose the optional secret token.

## Validation

- Node.js built-in test runner: 9 tests passed locally.
- `npm run check`: syntax validation and all regression tests passed locally.
- Node 20 and Node 22 CI plus a clean Docker image build are required before merge.
- The Actor pins the top-level runtime to `apify@3.7.2`, caps input size, and uses no LLM or paid external API. Transitive dependencies will be resolved and audited by clean CI and Docker builds before merge.

## Commercial status and next action

The code is a completed publication candidate, not income. No Apify account, Store listing, pricing, customer execution, approved payout, or cash receipt is claimed.

After CI succeeds, verify Japan-resident publisher eligibility, AI-assisted code eligibility, payout methods, fees, and Store publication requirements with Apify. Account creation, identity/payment setup, and final terms acceptance remain fail-closed until their conditions are clear. No fee, deposit, ad purchase, or paid plan will be authorized.
