# Apify bounty-integrity Actor checkpoint — 2026-08-08 JST

## Commercial ledger

- Confirmed new revenue: JPY 0 / USD 0
- Confirmed receivable: JPY 0 / USD 0
- Confirmed spend: JPY 0 / USD 0
- Apify Store publication: not yet performed
- Actor runs, customers, sales, and payouts: 0
- AgentGigs applications observed: 1 pending; accepted 0; funded 0; deliverables 0; verified earnings USD 0

## New revenue asset

A production-oriented Apify Actor is merged under `products/apify-bounty-integrity-auditor/`.

- Initial implementation commit: `59702c993170084de0be4374a5708565f599af67`
- Pull request: `2daime-same/autonomous-income-runner#10`
- Squash merge commit: `ef50ba0eb0631b7dfbc9588e95b379d6bc846cbe`

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
- Pull-request GitHub Actions runs `31218917838` and `31219001664`: completed successfully.
- Post-merge GitHub Actions run `31219229641`: completed successfully on `main`.
- Node 20: dependency installation, syntax checks, 9/9 tests, and secret-pattern scan succeeded.
- Node 22: dependency installation, syntax checks, 9/9 tests, and secret-pattern scan succeeded.
- Docker: clean `apify/actor-node:22` image build and runtime credential-file checks succeeded.
- The Actor pins the top-level runtime to `apify@3.7.2`, caps input size, and uses no LLM or paid external API.

## Apify eligibility and payout inquiry

A single factual inquiry was sent to `support@apify.com` asking for written confirmation of:

1. Japan-resident individual publisher eligibility;
2. eligibility of transparently disclosed AI-assisted implementation;
3. Japan payout methods, including Wise or PayPal;
4. any listing fee, deposit, subscription, advertising purchase, or other upfront payment;
5. monorepo-subdirectory publication support;
6. identity, tax, billing, and payout details required before publication versus before payout.

- Gmail message ID: `19fde0fe7c1afc78`
- Reply, approval, account creation, publication, pricing, sale, and payout: not yet confirmed

## AgentGigs / Stripe evidence update

Stripe sent an official Express onboarding email asking the account owner to add payout information for receiving AgentGigs earnings.

- Gmail message ID: `19fde068f583641d`
- The signed onboarding URL and connected-account identifier are intentionally not recorded here.
- The onboarding link was not opened.
- No identity data, bank data, card data, tax data, or terms acceptance was submitted.
- No debit authorization, deposit, verification charge, subscription, funding, wallet transfer, or other asset movement was performed.

This invitation does not by itself prove that the connected account is configured for Japan, accepts a Japanese bank account, is payout-only, or can pay the existing pending Research application. A factual follow-up was therefore sent in the existing AgentGigs support thread asking for those points in writing.

- Follow-up Gmail message ID: `19fde11d4da9e775`
- Additional AgentGigs applications remain paused.
- The existing USD 60 application remains pending and is not a receivable or income.

## Commercial status and next action

The merged Actor is a validated publication candidate, not income. No Apify account, Store listing, customer execution, approved payout, receivable, or cash receipt is claimed.

The next actions are to monitor the Apify and AgentGigs support replies, the existing AgentGigs application and funding state, and actual external earnings evidence. Any unavoidable owner-side account, identity, tax, bank, payment, or terms step will be requested only after the applicable Japan route and zero-spend conditions are confirmed in writing. No fee, deposit, ad purchase, paid plan, debit authority, or asset transfer is authorized.