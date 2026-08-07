# Apify bounty-integrity Actor checkpoint — 2026-08-08 JST

## Commercial ledger

- Confirmed new revenue: JPY 0 / USD 0
- Confirmed receivable: JPY 0 / USD 0
- Confirmed spend: JPY 0 / USD 0
- Apify Store publication: not yet performed
- Actor runs, customers, sales, and payouts: 0

## New revenue asset

A production-oriented Apify Actor was implemented under `products/apify-bounty-integrity-auditor/` and opened as draft PR #10.

- Branch: `agent/apify-bounty-integrity-auditor`
- Initial implementation commit: `59702c993170084de0be4374a5708565f599af67`
- Pull request: `2daime-same/autonomous-income-runner#10`

The Actor accepts public GitHub issue URLs and checks canonical issue and comment evidence before a developer or coding agent spends time on a purported paid task. It detects:

- open/closed state and public reward evidence;
- IssueHunt, Algora, and Opire provider signals;
- already-referenced or submitted pull requests;
- maintainer hold-offs and duplicate-work warnings;
- requests for hidden prompts, credentials, private keys, private payout data, or artificial engagement;
- a deterministic verdict, blockers, evidence, confidence, and score.

It performs read-only GitHub API access. It does not execute issue text, clone or run third-party code, post comments, claim work, submit pull requests, or expose the optional secret token.

## Validation

- Local `npm run check`: syntax validation and 9/9 regression tests passed.
- GitHub Actions run `31218917838`: completed successfully.
- Node 20: dependency installation, syntax checks, 9/9 tests, and secret-pattern scan succeeded.
- Node 22: dependency installation, syntax checks, 9/9 tests, and secret-pattern scan succeeded.
- Docker: clean `apify/actor-node:22` image build and runtime credential-file checks succeeded.
- The Actor pins the top-level runtime to `apify@3.7.2`, caps input size, and uses no LLM or paid external API.

## Eligibility and payout inquiry

A single factual inquiry was sent to `support@apify.com` asking for written confirmation of:

1. Japan-resident individual publisher eligibility;
2. eligibility of transparently disclosed AI-assisted implementation;
3. Japan payout methods, including Wise or PayPal;
4. any listing fee, deposit, subscription, advertising purchase, or other upfront payment;
5. monorepo-subdirectory publication support;
6. identity, tax, billing, and payout details required before publication versus before payout.

- Gmail message ID: `19fde0fe7c1afc78`
- Reply, approval, account creation, publication, pricing, sale, and payout: not yet confirmed

## Commercial status and next action

The code is a validated publication candidate, not income. No Apify account, Store listing, customer execution, approved payout, receivable, or cash receipt is claimed.

The next action is to merge the validated code, monitor the support reply, and only then perform any unavoidable owner-side account, identity, tax, payment, or terms step. No fee, deposit, ad purchase, or paid plan is authorized.