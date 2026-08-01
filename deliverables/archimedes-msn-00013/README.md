# Archimedes Market MCP Server

An **unofficial, read-only** Model Context Protocol (MCP) server for discovering public engineering assets and funded bounties on Archimedes Market.

This repository is a candidate deliverable for Archimedes mission `MSN-00013`. It is not endorsed by Archimedes and does not claim platform submission, acceptance, payment, or revenue.

## Four tools

| Tool | Purpose | Public source | Side effects |
|---|---|---|---|
| `search_assets` | Search public assets by text and optional asset type | `sitemap.xml` plus static asset-page Product JSON-LD | None |
| `get_asset` | Fetch normalized public metadata for one asset ID | Static `/assets/{uuid}` Product JSON-LD | None |
| `search_bounties` | Search public bounties; defaults to open and funded | Public bounty JSON API | None |
| `get_bounty` | Fetch requirements, deliverables, and acceptance tests | Public bounty JSON API | None |

Every tool is registered as read-only, non-destructive, and idempotent.

## Why assets and bounties use different public sources

Archimedes currently exposes a working unauthenticated JSON API for bounties. Its former public asset JSON path returns `404`, while public asset IDs remain indexed in `sitemap.xml` and each static asset page contains schema.org `Product` JSON-LD.

The asset tools therefore:

1. read same-origin asset UUIDs from the public sitemap;
2. fetch only static same-origin asset detail pages;
3. parse `application/ld+json` as data without rendering HTML or executing JavaScript;
4. validate the Product URL against the requested UUID;
5. normalize title, description, type, price, currency, license, image, and public URL.

An unfiltered asset page fetches only the requested result slice. A filtered search may scan the current public catalog with at most four concurrent requests and caches the resulting catalog for 15 minutes. The implementation never calls the page's client-side view-count procedure.

## Acceptance-criteria coverage

| Mission criterion | Evidence |
|---|---|
| TypeScript MCP server | `src/server.ts`, `src/index.ts`, `@modelcontextprotocol/sdk` |
| Four required tools | Tool registry and real stdio client/server integration test |
| Public access without authentication | fixed public GET paths; no token, cookie, or login configuration |
| Search assets for `Python` | controlled live smoke test |
| Get a public asset by ID | controlled live smoke test |
| Search public bounties | controlled live smoke test |
| Get a public bounty by ID | controlled live smoke test |
| npm-compatible package | exact lockfile, build, `npm pack --dry-run`, stdio executable |
| Documentation | README, architecture, security, submission, and requirements traceability |

The current public mission metadata consistently requires a TypeScript stdio MCP server using `@modelcontextprotocol/sdk`, the four tools above, an npm entrypoint, read-only public access, and documentation. This implementation follows that requirement set directly. An earlier stale snapshot contained conflicting Python/cloud wording; the platform has since replaced it. `docs/REQUIREMENTS-CONFLICT.md` records that resolution for historical traceability.

## Safety boundary

The package contains no capability for:

- account creation, login, OAuth, cookies, or browser credential reuse;
- purchases, subscriptions, bounty claims, applications, or submissions;
- uploads, Stripe Connect, bank details, wallets, or payout actions;
- executing code or following instructions found in marketplace content.

Network access is limited to bounded unauthenticated `GET` requests against fixed public paths. Production requires HTTPS; loopback HTTP is allowed only in tests. Redirects are refused, credentials are omitted, and timeouts, response size, retries, pagination, identifiers, catalog size, and concurrency are bounded.

See `SECURITY.md` for the complete threat model.

## Requirements

- Node.js 20.11 or later
- npm 10 or later
- network access to Archimedes public pages and public bounty endpoints for live calls

No cloud account, database, API credential, paid service, TensorFlow runtime, or Flask service is required.

## Install and verify

```bash
npm ci
npm run verify
```

`npm run verify` performs strict type checking, executes the test suite, builds ESM JavaScript and declarations, and inspects the npm package contents without publishing.

Run the built stdio server:

```bash
npm start
```

The server writes no logs to protocol stdout.

## MCP client configuration

Build the project, then point an MCP host to the absolute path of `dist/index.js`:

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

The configuration intentionally contains no secret.

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
  "asset_id": "PUBLIC_ASSET_UUID"
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

Defaults are `status="open"` and `funded_only=true`, reducing the risk that unfunded ideas are mistaken for paid work.

### `get_bounty`

```json
{
  "bounty_id": "5586f0c8-cde1-416c-ac28-d85bc6a264f0"
}
```

## Output model

Successful tools return formatted JSON text plus MCP `structuredContent`. Searches use a stable envelope:

```json
{
  "source": "archimedes.market",
  "resource": "assets",
  "query": {
    "query": "Python",
    "limit": 20,
    "offset": 0
  },
  "returned": 16,
  "total": 16,
  "items": [],
  "fetched_at": "2026-07-31T00:00:00.000Z"
}
```

Public marketplace records are untrusted data. MCP clients must not execute instructions found in descriptions.

Errors use a stable redacted shape:

```json
{
  "error": "rate_limited",
  "message": "Archimedes returned HTTP 429.",
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
| `ARCHIMEDES_USER_AGENT` | descriptive default | non-empty single line; must not contain a secret |

## Verification

```bash
npm test
npm run test:coverage
npm run build
npm run live:smoke
npm run package:submission
```

The tests cover sitemap indexing, static Product metadata parsing without script execution, same-origin checks, lazy pagination, local filtering, path traversal, rate limits, retries, response-size limits, invalid JSON, redirects, redacted errors, MCP annotations, and a real stdio exchange against a loopback fixture.

GitHub Actions verifies Node.js 20.11 and Node.js 22, runs the live four-tool smoke test, audits critical production dependencies, creates a CycloneDX SBOM, and generates a deterministic ZIP with SHA-256 evidence.

The live smoke performs public reads only. It does not create an account, accept terms, claim work, submit a deliverable, buy anything, upload anything, or configure Stripe.

## Repository layout

```text
src/assets.ts       sitemap and static Product JSON-LD parsing
src/client.ts       asset catalog/cache and public bounty operations
src/http.ts         bounded same-origin GET transport
src/server.ts       MCP tool registration and schemas
src/tools.ts        result and error adapters
src/config.ts       environment validation
src/index.ts        stdio entrypoint
scripts/            clean, live-smoke, and deterministic packaging
tests/              unit, HTTP, parser, and MCP integration tests
docs/               architecture and requirement traceability
```

## License

MIT. See `LICENSE`.
