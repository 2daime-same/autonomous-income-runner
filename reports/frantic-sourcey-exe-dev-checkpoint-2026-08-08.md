# Frantic / Sourcey exe.dev checkpoint — 2026-08-08 JST

## Commercial ledger

- Confirmed new revenue: JPY 0 / USD 0 / USDC 0
- Confirmed receivable: JPY 0 / USD 0 / USDC 0
- Confirmed spend: JPY 0 / USD 0 / USDC 0
- Mission complete: no

## AgentGigs status refreshed

The existing account `BoundaryLedger Agent 097062` remains reused and verified. The USD 60 Research application remains pending.

- applications observed: 1
- pending: 1
- accepted: 0
- funded: 0
- deliverables submitted: 0
- verified earnings: USD 0
- relevant notifications: 0
- additional applications: paused while AgentGigs clarifies Japan payout eligibility and inconsistent Stripe enforcement

A Gmail search found no new AgentGigs acceptance, assignment, funding, customer reply, payment, payout, or support response. The only new payout-related inbound item remains Stripe's Express onboarding invitation. No signed link was opened and no identity, bank, tax, card, terms, debit authorization, deposit, subscription, verification charge, or other asset movement was performed.

## Frantic funded opportunity

Frantic bounty #120, mirrored as `auscaster/frantic-board#330`, offers USD 1 per accepted Sourcey startup-offer record. The public issue was funded and showed open capacity when checked.

The acceptance gate is stricter than merely opening a pull request: Sourcey must complete human review, merge the contribution, and publish the vendor on a live Sourcey surface. Therefore this is not a receivable until those external gates pass.

Frantic bounty #97 was rejected because it requires the participant to fund a bounty of at least USD 10 and pay another worker. That violates the mission's absolute zero-spend rule.

## Selected Sourcey record

Selected vendor: `exe.dev`

First-party source: `https://exe.dev/startup`

Verified public facts used in the record:

- USD 10,000 in exe.dev startup credits
- credits valid for 12 months
- applicant is pre-Series-B
- company is less than five years old
- applicant has not received exe.dev startup credits before
- application is subject to manual review

Immediately before finalizing the candidate, `vendors/ex/exe-dev.yaml` was absent from Sourcey `main`, and Sourcey issue and pull-request searches for `exe.dev`, `exe dev`, `exe-dev`, and the program name returned no matches.

## Completed submission asset

Prepared files:

- `deliverables/frantic-120-exe-dev/vendors/ex/exe-dev.yaml`
- `deliverables/frantic-120-exe-dev/MISSING_RECORD_ISSUE.md`
- `deliverables/frantic-120-exe-dev/PR_BODY.md`
- `.github/workflows/validate-frantic-exe-dev.yml`

The workflow creates a synthetic Sourcey commit containing exactly one changed data file and a DCO sign-off, then downloads Sourcey's exact pinned production Catalog Verifier, verifies its checksum, and runs production `validate-change` against current Sourcey `main`.

Validation runs `31239010427` and `31239134403` succeeded, including:

- exact one-file data-only scope
- DCO sign-off
- pinned verifier checksum
- Sourcey production changed-closure validation
- credential-pattern scan

Dedicated-repository PR #11 was squash-merged. Merge commit: `caa21d7ae76ad905337ed7b2ba7363f823fd9a0d`.

## External submission blocker

The connected GitHub app can read `sourcey/startup-credits`, but it cannot create an issue, fork, branch, or pull request there. An attempted Sourcey issue write returned HTTP 403. No Frantic account already associated with the mailbox was found.

The candidate is technically ready, but the following external chain has not occurred:

1. reserve the missing record in Sourcey;
2. fork `sourcey/startup-credits` to `2daime-same`;
3. copy the already validated one-file contribution into that fork;
4. open the upstream Sourcey pull request;
5. complete Frantic signup, email verification, wallet setup, claim, and submission before claim expiry;
6. receive Sourcey human review, merge, and live publication;
7. receive Frantic approval and payout.

No Sourcey issue, Sourcey fork, upstream pull request, Frantic claim, submission, receivable, or payment is claimed.

## Other direct-bounty screening

- Nexussyn Algora issue #4 offered 3 USDC but already had at least a dozen competing implementation pull requests; rejected for near-zero expected value.
- Agent Bounties tasks requiring a 0.01 USDC bond or self-funding were rejected under the zero-spend rule.
- No other currently observed Frantic bounty combined positive pay, zero spend, clear acceptance criteria, and realistic execution probability.

## Owner action gate

The smallest unavoidable owner action is to create a personal GitHub fork of `sourcey/startup-credits` under the `2daime-same` account. Do not edit files. Do not pay for anything. After the fork exists, the agent can add the already validated file, open the upstream pull request, and continue with the Sourcey and Frantic submission chain.

## Next action

Monitor the AgentGigs USD 60 application and support replies. In parallel, after the Sourcey fork exists, publish the verified exe.dev contribution upstream without changing its validated scope. Continue rejecting any task that requires fees, funding, bonds, gas, deposits, purchases, or asset transfers.