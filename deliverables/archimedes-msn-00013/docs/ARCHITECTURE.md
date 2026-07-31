# Architecture

The package is a local stdio MCP process with four read-only tools. It has no account session, write queue, database, browser, cloud deployment, or payment integration.

## Data flows

### Public assets

```text
MCP host
  -> Zod input validation
  -> ArchimedesPublicClient
  -> GET /sitemap.xml
  -> same-origin UUID index
  -> GET /assets/{uuid}
  -> parse schema.org Product JSON-LD as inert data
  -> normalize and cache public metadata
  -> MCP structured result
```

The public asset JSON endpoint currently returns `404`. The public sitemap and static Product metadata are therefore the supported read path.

Security and load properties:

- sitemap entries must be same-origin asset UUID URLs;
- detail Product URLs must match the requested UUID;
- HTML is never rendered and page JavaScript is never executed;
- URLs discovered inside descriptions are not followed;
- unfiltered pagination fetches only the requested slice;
- filtered search scans at most the configured public-catalog bound;
- scans use at most four concurrent requests and cache results for 15 minutes;
- unreadable or stale sitemap entries are skipped, while transport/security failures remain visible;
- the client-side view-count procedure is never invoked.

### Public bounties

```text
MCP host
  -> Zod input validation
  -> ArchimedesPublicClient
  -> bounded GET /api/public/bounties[/id]
  -> preserve public JSON as untrusted data
  -> local text/funding filter
  -> MCP structured result
```

Bounty search defaults to `status=open` and `funded_only=true`. This is a discovery guardrail, not proof of eligibility, acceptance, or payment.

## Modules

- `src/index.ts`: starts the stdio transport.
- `src/server.ts`: registers four tools with strict schemas and read-only annotations.
- `src/tools.ts`: emits JSON text and `structuredContent`; redacts unexpected errors.
- `src/client.ts`: coordinates the asset catalog, cache, pagination, public bounty calls, and stable result envelopes.
- `src/assets.ts`: validates sitemap URLs and extracts static schema.org Product metadata.
- `src/http.ts`: enforces same-origin fixed paths, GET-only access, HTTPS, response bounds, retries, and redirect refusal.
- `src/filter.ts`: deterministic case-insensitive local search over public JSON.
- `src/json.ts`: converts unknown payloads to JSON-safe values.
- `src/config.ts`: validates environment-controlled transport settings.

## Cache model

Asset IDs, normalized details, and a fully filtered catalog are held only in process memory. The default time-to-live is 15 minutes. There is no persistent store. Concurrent filtered searches share the same in-flight catalog promise, preventing duplicate full scans in one process.

## Failure model

Known upstream failures map to stable public codes such as `not_found`, `rate_limited`, `timeout`, `response_too_large`, and `invalid_response`. Unexpected errors return a generic `internal_error`. Stack traces, environment variables, response bodies, local paths, and underlying causes are not returned to MCP clients.

## Verification layers

- parser tests for sitemap origin/UUID controls and Product URL binding;
- HTTP tests for GET-only behavior, retries, response bounds, redirects, and traversal;
- client tests for lazy pagination, search filtering, cache behavior, and funded-bounty defaults;
- a real MCP stdio child process driven by the official MCP client SDK;
- live public smoke tests for all four tools;
- strict TypeScript builds on Node.js 20.11 and Node.js 22;
- npm package inspection, production dependency audit, CycloneDX SBOM, and deterministic ZIP packaging.
