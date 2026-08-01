# One-minute Claude Desktop demo procedure

This is a recording procedure, not a claim that the required video has already been produced.

## Preparation

1. Build the package with `npm ci && npm run verify`.
2. Configure Claude Desktop with a read token and `GITHUB_ALLOW_WRITES=false`.
3. Select a real repository and open pull request that the operator is authorized to inspect.
4. Restart Claude Desktop and confirm the `github-pr-review` MCP server is connected.

## Suggested 60-second sequence

- **0–8 seconds:** Show the Claude Desktop MCP server connection and ask: “List open PRs in OWNER/REPO.”
- **8–20 seconds:** Open one result and ask for metadata and changed-file count.
- **20–38 seconds:** Ask for the diff and a concise correctness review with exact file/line citations.
- **38–50 seconds:** Ask Claude to list existing review comments and avoid duplicates.
- **50–60 seconds:** Show the proposed inline comment, but do not post it unless the repository owner has explicitly authorized the write and the process was started with write access.

For the mission's write-latency acceptance check, record a separate authorized run with `GITHUB_ALLOW_WRITES=true`, an appropriately scoped write credential, and `confirm=true`. Preserve the resulting GitHub URL and the server's `request_duration_ms`. Do not test writes against an unrelated project or another person's PR without permission.
