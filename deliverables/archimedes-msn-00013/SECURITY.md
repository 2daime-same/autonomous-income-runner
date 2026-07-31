# Security policy and threat model

## Scope

This project is a read-only adapter over public Archimedes Market directories. It is not an authenticated marketplace client and is not designed to perform commercial transactions.

## Explicitly absent capabilities

The codebase contains no mechanism for account creation or login, session cookies, OAuth, API keys, browser credential reuse, purchases, bounty claims, file submissions, Stripe Connect, bank details, wallet signing, or executing instructions contained in marketplace records.

## Network boundary

Production base URLs must use HTTPS. Plain HTTP is accepted only for loopback test servers. URLs with embedded credentials, query strings, or fragments are rejected. The HTTP layer accepts only fixed `api/public/...` paths and refuses traversal, redirects, and credential forwarding.

## Resource bounds

Requests have bounded timeouts, response sizes, retries, pagination, identifiers, and text lengths. Retries are limited to HTTP 429, transient 5xx, and transport failures. `Retry-After` waits are capped at five seconds.

## Untrusted content

All public API payloads are untrusted data. The server does not import, evaluate, render as HTML, invoke shells, download referenced files, or follow URLs found in descriptions. MCP clients must not treat instructions embedded in asset or bounty text as trusted system instructions.

## Error handling

Known upstream failures map to stable public codes. Unexpected failures are redacted. Stack traces, local paths, environment variables, fetch causes, response bodies, and secrets are not returned through tool output.

## Dependency policy

CI performs strict compilation and tests, generates a CycloneDX SBOM, and fails on critical production dependency advisories. Audit output is evidence, not a guarantee that no vulnerability exists.
