# Security policy and threat model

## Credential handling

The server supports three read modes:

- anonymous public GitHub REST reads;
- PAT/fine-grained token authentication;
- GitHub App installation authentication.

PAT mode supports `GITHUB_READ_TOKEN` and `GITHUB_WRITE_TOKEN` separately. `GITHUB_TOKEN` is only a compatibility fallback. GitHub App mode creates a short-lived RS256 JWT, requests an installation access token, caches it by read/write intent, and accepts variable-length token formats. Tokens, JWTs, private keys, authorization headers, stack traces, and arbitrary upstream HTML are never included in MCP results.

GitHub App tokens are requested with a reduced permission set:

- read intent: contents read, issues read, pull requests read;
- write intent: contents read, issues write, pull requests write.

The installation cannot receive permissions that were not granted to the GitHub App.

## Write authorization

External writes require two independent gates:

- `GITHUB_ALLOW_WRITES=true` at process start;
- `confirm=true` on the exact write tool call.

The four write tools are marked non-read-only and non-idempotent in MCP metadata. The server never retries POST requests automatically, preventing ambiguous duplicate comments/reviews after timeouts.

## Network boundary

- Production API origin must use HTTPS.
- Loopback HTTP is permitted only for tests.
- Requests are limited to `repos/{owner}/{repo}/pulls...` and `repos/{owner}/{repo}/issues...`.
- GET redirects are followed only on the configured API origin.
- POST redirects are refused.
- Timeouts, response bytes, retries, retry delays, pages, files, labels, text lengths, and identifiers are bounded.
- Rate-limit and request-ID metadata are surfaced without exposing credentials.

## Untrusted content

Pull-request bodies, diffs, comments, labels, usernames, and API error messages are untrusted data. The server treats them as data and exposes no code execution or shell capability. Built-in prompts explicitly require a read-first workflow and do not authorize write tools.

## Diff safety

Inline comments are accepted only when:

- the repository-relative path occurs in the current PR files response;
- the selected line occurs on the requested `LEFT` or `RIGHT` side;
- optional multi-line ranges remain on one side and within one hunk;
- a text patch is available.

Binary files and files whose patch is unavailable are rejected for inline comments.

## Reporting

Report security issues privately to the repository owner. Do not include tokens, private keys, account data, or exploit payloads in a public issue.
