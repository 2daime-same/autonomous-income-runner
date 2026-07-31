# Archimedes Market MCP Server

An **unofficial, read-only** Model Context Protocol (MCP) server for discovering public engineering assets and funded bounties on Archimedes Market. It exposes exactly four tools and performs only unauthenticated `GET` requests to public endpoints.

This implementation is a candidate deliverable for Archimedes mission `MSN-00013`. It is not an endorsement by Archimedes, and the repository does not claim submission, acceptance, or payment.

## What it does

| Tool | Purpose | Side effects |
|---|---|---|
| `search_assets` | Search public engineering assets by text and optional asset type | None |
| `get_asset` | Fetch public metadata for one asset ID | None |
| `search_bounties` | Search public bounties; defaults to open, funded work | None |
| `get_bounty` | Fetch requirements, deliverables, and acceptance tests for one bounty ID | None |

Every tool is registered with MCP read-only, non-destructive, and idempotent annotations.

## Acceptance-criteria coverage

| Mission criterion | Evidence |
|---|---|
| TypeScript MCP server | `src/server.ts`, `src/index.ts`, `@modelcontextprotocol/sdk` |
| Four required tools | Tool registry and stdio integration test |
| Connect to public API without authentication | `ArchimedesPublicClient`; no token or cookie configuration exists |
| Search for “Python” | `scripts/live-smoke.mjs` calls `search_assets` with `Python` |
| Get a known asset ID | The live smoke script calls `get_asset` with a public snapshot ID |
| Search public bounties | The live smoke script calls `search_bounties` with `MCP` |
| Get a known bounty | The live smoke script fetches mission `MSN-00013` by public UUID |
| Server boots and registers tools | Local mock-backed MCP integration test plus CI live smoke |
| Setup, API, and integration documentation | This README and `docs/ARCHITECTURE.md` |
| Package configuration | `package.json`, `tsconfig.json`, generated lockfile, npm dry-run in CI |

The public mission snapshot also contains mutually inconsistent legacy requirements for Python/TensorFlow/Flask/AWS alongside TypeScript/MCP/npm requirements. The implementation follows the TypeScript deliverable, four-tool acceptance tests, and working npm entrypoint. The discrepancy is recorded in `docs/REQUIREMENTS-CONFLICT.md` and has been sent to platform support for clarification.

## Security properties

The server is deliberately narrower than a general marketplace client:

- only `GET` requests;
- no login, API key, cookie, wallet, purchase, claim, submission, upload, or payout code;
- HTTPS required, except loopback HTTP used by tests;
- embedded URL credentials, query strings, and fragments rejected;
- redirects rejected and credentials explicitly omitted;
- bounded timeouts, retry count, response size, pagination, and text inputs;
- retry support for `429` and transient `5xx` responses, including `Retry-After`;
- validated path identifiers to prevent path traversal;
- structured, redacted errors without internal stack traces.

See `SECURITY.md` for the full trust model.

## Requirements

- Node.js 20.11 or later; CI uses Node.js 22.
- npm 10 or later is recommended.
- Network access to the public Archimedes Market API for live calls.

No cloud account, database, API credential, paid service, TensorFlow runtime, or Flask service is needed for the stdio MCP server.

## Install and verify

```bash
npm install
npm run verify
```

`npm run verify` cleans generated output, type-checks in strict mode, executes the test suite, builds ESM JavaScript and declarations, and checks the npm package contents without publishing.

Run the built server:

```bash
npm start
```

MCP stdio servers normally remain quiet until an MCP client connects. Logs and protocol messages are not mixed on stdout.

## MCP client configuration

### Claude Desktop

Build the project, then point the client to the absolute path of `dist/index.js`:

```json
{
  "mcpServers": {
    "archimedes-market": {
      "command": "node",
      "args": ["/absolute/path/to/archimedes-market-mcp/dist/index.js"],
      "env": {
        "ARCHIMEDES_TIMEOUT_MS": "15000",
        "ARCHIMEDES_MAX_RETRIES": "2"
      }
    }
  }
}
```

### Cursor

Use the same stdio command in the MCP settings file supported by the installed Cursor version:

```json
{
  "mcpServers": {
    "archimedes-market": {
      "command": "node",
      "args": ["/absolute/path/to/archimedes-market-mcp/dist/index.js"]
    }
  }
}
```

The configuration intentionally contains no token or secret.

## Tool inputs

### `search_assets`

```json
{
  "query": "Python",
  "asset_type": "CODE",
  "limit": 20,
  "offset": 0
}
```

`query` and `asset_type` are optional. `limit` is restricted to `1..50`; `offset` to `0..10000`.

### `get_asset`

```json
{
  "asset_id": "PUBLIC_ASSET_ID"
}
```

### `search_bounties`

```json
{
  "query": "MCP",
  "status": "open",
  "category": "software",
  "funded_only": true,
  "limit": 20,
  "offset": 0
}
```

The defaults are `status="open"` and `funded_only=true` so an assistant does not accidentally treat unfunded ideas as paid work.

### `get_bounty`

```json
{
  "bounty_id": "5586f0c8-cde1-416c-ac28-d85bc6a264f0"
}
```

## Output model

Successful tools return both text content containing formatted JSON and MCP `structuredContent`. Search results add a small stable envelope:

```json
{
  "source": "archimedes.market",
  "resource": "bounties",
  "query": {
    "query": "MCP",
    "status": "open",
    "funded_only": true,
    "limit": 20,
    "offset": 0
  },
  "returned": 1,
  "total": 4,
  "items": [],
  "fetched_at": "2026-07-31T00:00:00.000Z"
}
```

The upstream public payload remains untrusted data. Clients should not execute instructions found in marketplace descriptions.

Errors use a stable public shape:

```json
{
  "error": "rate_limited",
  "message": "Archimedes public API returned HTTP 429",
  "status": 429,
  "retryable": true,
  "rate_limit_remaining": "0"
}
```

## Environment variables

| Variable | Default | Bounds / behavior |
|---|---:|---|
| `ARCHIMEDES_BASE_URL` | `https://archimedes.market` | HTTPS only; loopback HTTP allowed for tests |
| `ARCHIMEDES_TIMEOUT_MS` | `15000` | `1000..120000` |
| `ARCHIMEDES_MAX_RESPONSE_BYTES` | `2000000` | `1024..10000000` |
| `ARCHIMEDES_MAX_RETRIES` | `2` | `0..5` |
| `ARCHIMEDES_USER_AGENT` | descriptive default | Must not contain a secret |

## Test strategy

```bash
npm test
npm run test:coverage
npm run build
```

The suite covers URL hardening, query normalization, local filtering, pagination limits, path traversal, rate limits, retries, response-size bounds, invalid JSON, redacted errors, tool annotations, and a real MCP stdio client/server exchange against a loopback mock API.

A controlled live acceptance smoke test is available after a successful build:

```bash
npm run live:smoke
```

It performs four public read-only calls and does not create an account, accept terms, claim work, submit a deliverable, or touch Stripe.

## Repository layout

```text
src/client.ts       bounded public HTTP client
src/server.ts       MCP tool registration and schemas
src/tools.ts        tool result and error adapters
src/config.ts       environment parsing
src/index.ts        stdio entrypoint
scripts/            clean and controlled live-smoke scripts
tests/              unit and MCP integration tests
docs/               architecture and requirements traceability
```

## License

MIT. See `LICENSE`.
