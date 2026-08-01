# Archimedes GitHub PR MCP Server

A permission-gated Model Context Protocol server for listing, inspecting, commenting on, reviewing, and labeling GitHub pull requests.

This repository is a candidate deliverable for Archimedes funded mission `MSN-00015`. It is not endorsed by GitHub or Archimedes and does not claim platform submission, acceptance, npm publication, payment, or revenue.

## Capabilities

### Read tools

| Tool | Purpose |
|---|---|
| `list_prs` | List open/closed/all PRs with bounded pagination |
| `get_pr` | Fetch normalized PR metadata, head/base SHAs, labels, reviewers, and change counts |
| `get_pr_diff` | Fetch changed files and parse hunks into commentable `LEFT`/`RIGHT` lines |
| `list_pr_comments` | Combine issue conversation comments, review summaries, and inline review comments |

### Write tools

| Tool | Purpose |
|---|---|
| `post_review_comment` | Post an immediate inline comment after validating the current diff location |
| `submit_review` | Create a review or submit an existing pending review |
| `add_labels` | Add existing repository labels to a PR |
| `request_changes` | Submit a dedicated `REQUEST_CHANGES` review |

Every write tool requires both:

1. `GITHUB_ALLOW_WRITES=true` when the process starts; and
2. `confirm=true` in the exact tool call.

POST requests are never retried automatically.

### Opt-in prompts

- `review_pr_correctness`
- `review_pr_security`

Both prompts instruct the model to inspect metadata, diffs, and comments first. They do not authorize write tools.

## Requirements

- Node.js 20.11 or later
- npm 10 or later
- an MCP host that supports stdio, such as Claude Desktop or Cursor
- optional GitHub authentication for private repositories or higher rate limits
- write-capable GitHub permissions only when write tools are deliberately enabled

## Install from source

```bash
npm ci
npm run verify
npm start
```

`npm run verify` performs strict type checking, runs all tests, builds ESM JavaScript and declarations, and inspects the npm package contents without publishing.

After an authorized npm publication, the intended invocation is:

```bash
npx -y archimedes-github-pr-mcp@1.0.0
```

The package is not yet published; do not rely on that command until the npm publication is independently confirmed.

## Authentication

### Public anonymous reads

```bash
GITHUB_AUTH_MODE=none npm start
```

This can read public repositories within GitHub's anonymous rate limit. Write tools remain unavailable.

### PAT or fine-grained token

Use separate credentials when possible:

```bash
export GITHUB_AUTH_MODE=pat
export GITHUB_READ_TOKEN='...'
export GITHUB_WRITE_TOKEN='...'
export GITHUB_ALLOW_WRITES=false
npm start
```

`GITHUB_TOKEN` is a compatibility fallback used for both intents when the separate variables are absent.

Recommended fine-grained repository permissions:

- read-only operation: Contents read, Issues read, Pull requests read;
- reviews/comments: Pull requests write;
- labels: Issues write;
- Contents read remains useful for repository metadata and app scoping.

### GitHub App installation

```bash
export GITHUB_AUTH_MODE=app
export GITHUB_APP_ID='12345'
export GITHUB_APP_INSTALLATION_ID='67890'
export GITHUB_APP_PRIVATE_KEY='-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----'
export GITHUB_ALLOW_WRITES=false
npm start
```

`GITHUB_APP_PRIVATE_KEY_BASE64` can be used instead of PEM text. The server creates a short-lived RS256 app JWT and requests separate reduced-permission installation tokens for read and write intent. Installation tokens are treated as opaque variable-length strings and cached until shortly before expiry.

## Claude Desktop configuration

Build the project, then point Claude Desktop at `dist/index.js`:

```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "node",
      "args": ["/absolute/path/to/archimedes-github-pr-mcp/dist/index.js"],
      "env": {
        "GITHUB_AUTH_MODE": "pat",
        "GITHUB_READ_TOKEN": "YOUR_READ_TOKEN",
        "GITHUB_ALLOW_WRITES": "false"
      }
    }
  }
}
```

For write operations, use a separately reviewed write token and change `GITHUB_ALLOW_WRITES` to `true`. The individual write call must still include `confirm=true`.

## Cursor configuration

A local stdio configuration uses the same command and environment boundary:

```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "node",
      "args": ["/absolute/path/to/archimedes-github-pr-mcp/dist/index.js"],
      "env": {
        "GITHUB_AUTH_MODE": "pat",
        "GITHUB_READ_TOKEN": "YOUR_READ_TOKEN",
        "GITHUB_ALLOW_WRITES": "false"
      }
    }
  }
}
```

Do not commit tokens or private keys into a Cursor project file.

## Typical read-first workflow

1. `list_prs` to identify the target.
2. `get_pr` to understand head/base, size, labels, and review state.
3. `get_pr_diff` to inspect changed files and exact diff coordinates.
4. `list_pr_comments` to avoid repeating existing review findings.
5. Present findings to the user.
6. Only after an explicit user instruction, call one narrowly scoped write tool with `confirm=true`.

## Inline diff coordinates

GitHub review comments use diff-side coordinates:

- `RIGHT` corresponds to the new/head side;
- `LEFT` corresponds to the old/base side;
- additions exist only on `RIGHT`;
- deletions exist only on `LEFT`;
- context lines can be referenced on either side.

`get_pr_diff` returns parsed hunk lines with `oldLine` and `newLine`. `post_review_comment` re-fetches the current PR head and files, then refuses the write when the path, side, or line is no longer present. Multi-line ranges must remain within one hunk and one side.

Raw patch text is excluded by default; set `include_patch=true` when it is specifically needed. Parsed hunks are always returned. GitHub can omit a patch for binary or very large files; those files cannot receive inline comments through this server.

## Pagination and rate limits

- GitHub list calls use `per_page=100`.
- The process bounds pages, files, response bytes, timeouts, retry counts, and retry delays.
- Only GET requests are retried.
- `Retry-After` and primary rate-limit reset headers are respected within a configured maximum wait.
- Secondary rate-limit responses are surfaced as retryable read errors.
- Results include limit, remaining, used, reset time, resource, and GitHub request ID when provided.

## Environment variables

| Variable | Default | Behavior |
|---|---:|---|
| `GITHUB_API_BASE_URL` | `https://api.github.com` | HTTPS; loopback HTTP only in tests |
| `GITHUB_API_VERSION` | `2026-03-10` | GitHub REST API version header |
| `GITHUB_AUTH_MODE` | `auto` | `auto`, `none`, `pat`, or `app` |
| `GITHUB_ALLOW_WRITES` | `false` | Process-level write gate |
| `GITHUB_TIMEOUT_MS` | `15000` | `1000..120000` |
| `GITHUB_MAX_RESPONSE_BYTES` | `5000000` | `16384..25000000` |
| `GITHUB_MAX_RETRIES` | `2` | GET retries only, `0..5` |
| `GITHUB_MAX_RETRY_DELAY_MS` | `5000` | Capped wait, `0..30000` |
| `GITHUB_MAX_PAGES` | `5` | `1..20` |
| `GITHUB_MAX_FILES` | `500` | `1..3000` |

See `.env.example` for all credential variables.

## Verification

```bash
npm test
npm run test:coverage
npm run build
npm run live:smoke
npm run package:submission
```

The test suite covers:

- RS256 GitHub App JWT verification;
- variable-length installation tokens and caching;
- separate PAT read/write credentials and write gating;
- more-than-100-PR pagination;
- PR metadata, file diffs, and all comment surfaces;
- diff parsing and `LEFT`/`RIGHT` line validation;
- all four write request shapes;
- confirmation rejection;
- GET-only rate-limit retries;
- refusal to retry POST;
- same-origin redirects;
- response-size bounds;
- error and secret redaction;
- real stdio MCP client/server exchange.

The controlled live smoke calls only the four read tools against a selected real PR.

## Acceptance items not automated by this package

The Archimedes mission also calls for:

- npm publication;
- a one-minute Claude Desktop screen capture on a real repository;
- a manual check that a posted review comment appears within five seconds;
- a clean-machine quickstart review.

This repository provides the code, configuration, deterministic artifact, request-duration evidence, and demo procedure, but it does not falsely mark those human/platform steps complete.

## Repository layout

```text
src/auth.ts          PAT and GitHub App token providers
src/http.ts          bounded REST transport and rate-limit handling
src/diff.ts          unified-diff parsing and line validation
src/client.ts        eight PR operations
src/server.ts        MCP tools and opt-in prompts
src/index.ts         stdio entrypoint
tests/               unit and MCP integration tests
scripts/             smoke test, cleanup, deterministic packaging
docs/                architecture and demo procedure
```

## Official references

- GitHub App authentication: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app
- Pull-request reviews: https://docs.github.com/en/rest/pulls/reviews
- Pull-request review comments: https://docs.github.com/en/rest/pulls/comments
- REST rate limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- MCP TypeScript SDK v1: https://github.com/modelcontextprotocol/typescript-sdk/tree/v1.x

## License

MIT. See `LICENSE`.
