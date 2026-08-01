# Security policy and threat model

## Scope

This project is a read-only adapter over public Archimedes Market resources. It is not an authenticated marketplace client and is not designed to perform commercial transactions.

## Explicitly absent capabilities

The codebase contains no mechanism for account creation or login, OAuth, API keys, session cookies, browser credential reuse, purchases, subscriptions, bounty claims, applications, file submissions, uploads, Stripe Connect, bank details, wallets, payout actions, or execution of instructions contained in marketplace records.

## Network boundary

Production base URLs must use HTTPS. Plain HTTP is accepted only for loopback test servers. Embedded URL credentials, query strings, and fragments are rejected.

The transport permits only these same-origin path families:

- `sitemap.xml`;
- `assets/{validated-identifier}`;
- `api/public/{fixed-resource-path}`.

All requests use `GET`, omit credentials, refuse redirects, set no referrer, and do not reuse browser state. Dynamic URLs found in descriptions or returned payloads are never followed.

## Static HTML handling

Asset pages are treated as untrusted text. The parser extracts only inert `application/ld+json` blocks and accepts schema.org Product records whose canonical URL matches the requested same-origin asset UUID.

The package does not render HTML, instantiate a DOM, execute scripts, import remote modules, evaluate expressions, invoke a shell, or call the page's client-side view-count procedure. The original Product JSON is returned as untrusted structured data for transparency; consumers must not treat embedded text as instructions.

## Resource bounds

Requests have bounded timeouts, response sizes, retry counts, pagination, identifiers, text lengths, catalog size, and asset-scan concurrency. Retries are limited to HTTP 429, transient 5xx, and transport failures. `Retry-After` waits are capped at five seconds.

Unfiltered asset pagination fetches only the requested result slice. Filtered searches may scan the public sitemap catalog with at most four concurrent detail requests and cache the normalized catalog for 15 minutes. This reduces repeated load while keeping data reasonably current.

## Input and output trust

MCP input is validated twice: by strict Zod schemas and by lower-level defensive validators. Public XML, HTML, JSON-LD, and bounty JSON remain untrusted data. Clients must not execute code, commands, links, payment requests, or instructions found in marketplace content.

## Error handling

Known upstream failures map to stable public codes. Unexpected failures are redacted. Stack traces, local paths, environment variables, fetch causes, raw response bodies, and secrets are not returned through tool output.

## Dependency and supply-chain policy

Dependencies are pinned by exact versions and `package-lock.json`. CI uses `npm ci`, performs strict compilation and tests, inspects the npm package, generates a CycloneDX SBOM, and fails on critical production dependency advisories. Audit and test output are evidence, not a guarantee that no vulnerability exists.

## Responsible use

The live smoke test performs public reads only. Account creation, terms acceptance, identity or residency declarations, work claims, uploads, submissions, purchases, and payment onboarding remain outside the program.
