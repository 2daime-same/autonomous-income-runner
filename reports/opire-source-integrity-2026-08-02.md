# Opire source-integrity QA report — 2026-08-02

## Commercial status

- Verified income: **0**
- Verified receivable: **0**
- Expense: **0**
- Opire claim or account action performed: **none**

This report is a read-only QA deliverable. It does not assert that any displayed reward is payable.

## Finding

Opire's public available-rewards feed can retain records as open/actionable when the canonical GitHub source is deleted, closed, renamed without a valid issue, or missing. This can inflate opportunity rankings and send developers toward work with no valid submission path.

## Reproduction matrix

| Opire opportunity | Displayed state | Canonical GitHub validation on 2026-08-02 | Execution decision |
|---|---|---|---|
| `Asynchronous Web APIs` — `uswriting/zeroperl`, `$1,500`, 0 solvers | Open / available | `https://github.com/uswriting/zeroperl/issues/7` redirects to `6over3/zeroperl/issues/7`; GitHub states **This issue has been deleted** | Reject |
| `Close Request Body on Authentication Middleware Early-Return to Prevent Connection Leaks` — `madalynerlge2/gin`, `$100`, 0 solvers | Recently listed as available | `https://github.com/madalynerlge2/gin/issues/1` is **closed as not planned**; repository is unrelated to upstream `gin-gonic/gin`; near-duplicate issue #2 exists | Reject |
| `Images on the bottom of level up messages` — `buape/kiai-bounties`, `$20`, 0 solvers | Listed as available | Repository and issues URLs return **404** | Reject |
| `research implementation for Windows` — `radumarias/rencfs`, `$42`, 0 solvers | Listed as available | Repository exists, but its GitHub open-issues page contains **no open issues** | Reject until canonical issue is identified and open |

## Evidence URLs

### Deleted source issue

- Opire: `https://app.opire.dev/issues/01JN06N9GS8Q1KB2NJ318258HR`
- Source recorded by Opire: `https://github.com/uswriting/zeroperl/issues/7`
- Canonical redirect target: `https://github.com/6over3/zeroperl/issues/7`

### Closed / provenance-mismatched source

- Repository: `https://github.com/madalynerlge2/gin`
- Closed issue: `https://github.com/madalynerlge2/gin/issues/1`
- Near-duplicate issue: `https://github.com/madalynerlge2/gin/issues/2`
- Expected upstream project referred to by the brief: `https://github.com/gin-gonic/gin`

### Missing repository

- `https://github.com/buape/kiai-bounties`
- `https://github.com/buape/kiai-bounties/issues`

### No open source issue

- `https://github.com/radumarias/rencfs`
- `https://github.com/radumarias/rencfs/issues`

## Impact

1. High-value deleted records can outrank real opportunities.
2. Solvers can spend hours on code that has no valid issue or claim route.
3. Available reward counts and aggregate open value may include non-actionable records.
4. Thin repositories can present briefs that appear to refer to established upstream code, creating provenance and marketplace-quality risk.
5. Automated bounty clients must independently validate every GitHub source rather than trust the marketplace state.

## Expected behavior

Before a reward appears in an actionable feed:

1. Resolve repository renames and persist the canonical repository.
2. Fetch the canonical repository and issue.
3. Require a public, non-disabled, non-missing repository.
4. Require an existing, currently open issue rather than a PR, deleted issue, or closed issue.
5. Confirm that the issue belongs to the repository containing the implementation target.
6. Keep invalidated reward history for audit without counting it as available work.
7. Revalidate before search ranking, available-count calculation, and claim initiation.

## Acceptance cases

- Renamed repository + live open issue → update canonical URL and retain opportunity.
- Renamed repository + deleted issue → remove from actionable feed.
- Closed/not-planned issue retaining reward labels → remove from actionable feed.
- Repository 404 → remove and flag for review.
- Repository exists but canonical issue cannot be identified → quarantine rather than rank.
- Reopened issue → return only after a fresh validation.
- Aggregate available count/value excludes all failed source validations.

## External report status

Sent to `team@opire.dev` on 2026-08-02 with an optional request for a `$1` Opire QA tip to GitHub user `@2daime-same` if the defect is verified. No response, tip, receivable, or payment has been confirmed at the time of this report.
