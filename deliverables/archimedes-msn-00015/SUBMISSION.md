# Submission brief — Archimedes MSN-00015

## Candidate deliverable

- Mission: `MSN-00015`
- Public title: `Build an MCP Server that Lets Claude Triage and Review GitHub PRs`
- Implementation: TypeScript stdio MCP server
- License: MIT
- Package: `archimedes-github-pr-mcp`
- Platform submission status: **not submitted**
- Acceptance status: **not accepted**
- npm publication status: **not published**
- Demo-video status: **not recorded**
- Verified revenue or receivable: **0**

A funded/locked mission is an opportunity signal, not income or a receivable.

## Requirement coverage

| Mission item | Candidate evidence |
|---|---|
| TypeScript MCP server | `src/server.ts`, `src/index.ts`, SDK dependency |
| npm-compatible entrypoint | `bin`, `npm start`, deterministic package |
| `list_prs` | bounded 100-item pagination, normalized PR metadata |
| `get_pr` | head/base, reviewers, labels, counts, merge state |
| `get_pr_diff` | file pagination, unified-diff hunks, LEFT/RIGHT lines |
| `list_pr_comments` | issue comments, review summaries, inline comments |
| `post_review_comment` | current-head pinning and diff-location validation |
| `submit_review` | create or submit COMMENT/APPROVE/REQUEST_CHANGES reviews |
| `add_labels` | issue-label endpoint with bounded deduplicated labels |
| `request_changes` | dedicated REQUEST_CHANGES review tool |
| PAT auth | separate read/write tokens plus compatibility fallback |
| GitHub App auth | RS256 JWT and scoped installation tokens |
| Rate-limit awareness | response metadata and capped GET-only retry waits |
| Pagination | configurable bound, up to 100 items per GitHub page |
| Inline diff resolution | path, hunk, side, and line checks before POST |
| Opt-in review prompts | correctness and security MCP prompts |
| Write permission model | process-level enablement plus per-call confirmation |

## Reproduction

```bash
npm ci
npm run verify
```

Read-only live smoke testing requires an existing PR:

```bash
GITHUB_AUTH_MODE=pat \
GITHUB_READ_TOKEN=... \
GITHUB_SMOKE_OWNER=OWNER \
GITHUB_SMOKE_REPO=REPO \
GITHUB_SMOKE_PR=123 \
npm run live:smoke
```

The smoke test calls only the four read tools. It does not post comments, submit reviews, add labels, or request changes.

## Remaining human/platform steps

The following are intentionally not represented as complete:

- create or select the submission account;
- confirm Japan-based eligibility and AI-assisted authorship with Archimedes;
- publish the package to npm under an authorized account;
- configure Claude Desktop with an authorized GitHub credential;
- record the required one-minute Claude Desktop demonstration on a real repository;
- perform any manual five-second visibility acceptance check;
- perform a clean-machine quickstart review;
- upload the final repository/package/video to Archimedes;
- accept terms, provide warranties, or configure identity/tax/payout details.

Those actions require the human account owner or an authorized platform operator.
