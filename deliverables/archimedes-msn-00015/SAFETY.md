# Safety boundary

This package can perform external writes only when **both** safeguards are present:

1. the process was started with `GITHUB_ALLOW_WRITES=true`; and
2. the individual MCP call includes `confirm=true`.

A model cannot enable the environment variable through any registered tool. The server exposes no shell, file-writing, repository-content, branch, merge, account, billing, or token-management tool.

## Read tools

- `list_prs`
- `get_pr`
- `get_pr_diff`
- `list_pr_comments`

Public repositories can be read without authentication. Private repositories require an appropriately limited credential.

## Write tools

- `post_review_comment`
- `submit_review`
- `add_labels`
- `request_changes`

Write requests are never automatically retried. Inline comments are validated against the current GitHub diff before the POST is sent. The returned request duration is evidence of the API round trip, not proof that a human viewed the comment.

## Human-controlled actions

This code does not:

- create GitHub or Archimedes accounts;
- accept platform terms;
- create or install a GitHub App;
- generate or store PATs/private keys;
- publish an npm package;
- upload or submit an Archimedes mission;
- configure Stripe, banking, tax, identity, or payout information;
- claim payment, acceptance, revenue, or a receivable.

Credentials are supplied by the operator at process start and remain outside generated artifacts.
