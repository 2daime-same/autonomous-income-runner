# Operational safety

The package exposes four public-data tools. Each tool is read-only.

- Requests use the `GET` method and fixed public endpoint prefixes.
- HTTPS is required outside local test fixtures.
- Redirects are rejected.
- Text, pagination, identifiers, timeout, retry count, and response size are bounded.
- Returned marketplace text remains data; the process does not execute it or open embedded links.
- Unexpected failures return a generic result without implementation details.

The package has no account, order, claim, submission, upload, contract, or payment operation. It uses no private API configuration.

CI checks types, tests, package contents, production dependencies, an SBOM, and the final ZIP manifest.
