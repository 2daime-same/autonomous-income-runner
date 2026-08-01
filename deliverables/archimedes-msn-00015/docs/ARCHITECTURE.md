# Architecture

## Components

```text
MCP host
  │ stdio
  ▼
McpServer / schemas / prompts
  │
  ▼
GitHubPullRequestClient
  ├─ read operations
  ├─ diff parsing and location validation
  └─ permission-gated write operations
        │
        ▼
GitHubHttpClient
  ├─ bounded GET retry policy
  ├─ no automatic POST retries
  ├─ same-origin redirect enforcement
  ├─ response-size and timeout limits
  └─ redacted structured errors
        │
        ▼
GitHubTokenProvider
  ├─ anonymous
  ├─ separate PAT read/write credentials
  └─ GitHub App installation tokens
```

## Read flow

1. Zod validates the MCP input.
2. Identifier validation constructs a fixed GitHub REST path.
3. The token provider returns a read token or `null` for public access.
4. The HTTP client performs a bounded GET.
5. List endpoints paginate at 100 items per page within configured limits.
6. Responses are normalized and accompanied by rate-limit/request metadata.

## Write flow

1. The schema requires literal `confirm=true`.
2. The client repeats the confirmation check.
3. The token provider rejects writes unless `GITHUB_ALLOW_WRITES=true`.
4. A write credential or GitHub App installation token is required.
5. Inline comments additionally fetch the current PR head and file patches and validate the requested location.
6. Exactly one POST is issued. It is never retried automatically.
7. The normalized response includes the resulting GitHub URL and API round-trip duration.

## Diff model

The parser converts unified diff hunks into lines with:

- patch position;
- kind: context, addition, or deletion;
- old (`LEFT`) line number;
- new (`RIGHT`) line number;
- text.

Context lines can exist on both sides. Deletions exist only on `LEFT`; additions only on `RIGHT`. Multi-line comments must remain within one hunk and one side.

## Authentication

### PAT

`GITHUB_READ_TOKEN` and `GITHUB_WRITE_TOKEN` allow least-privilege separation. `GITHUB_TOKEN` is a fallback for environments that supply only one token.

### GitHub App

The server signs a JWT using RS256 with a short lifetime, then calls the installation access-token endpoint. Read and write tokens are separately cached and requested with reduced permissions. Installation tokens are treated as opaque variable-length strings.

## Failure semantics

Stable errors distinguish invalid input, disabled writes, missing authentication, rate limits, upstream validation failures, missing resources, oversized responses, refused redirects, and internal failures. Causes and stacks are not returned to MCP clients.
