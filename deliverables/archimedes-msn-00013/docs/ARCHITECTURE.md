# Architecture

The package is a local stdio MCP process with four read-only tools.

```text
MCP host -> Zod tool schema -> typed handler -> bounded public HTTP client -> Archimedes public API
```

## Modules

- `src/index.ts`: starts the stdio transport.
- `src/server.ts`: registers the four tool schemas and read-only annotations.
- `src/tools.ts`: returns text plus structured MCP results.
- `src/client.ts`: builds fixed public URLs, sends GET requests, parses JSON, applies bounds, and reports public errors.
- `src/config.ts`: validates timeout, retry, response-size, and base-URL settings.

## Data flow

1. The MCP SDK validates the tool arguments.
2. The handler invokes one client method.
3. The client requests one fixed public endpoint.
4. Search results receive a stable envelope; detail results preserve public JSON.
5. The handler returns JSON text and `structuredContent`.

The server has no database, browser process, account session, cloud service, or write queue.

## Verification layers

- unit tests for arguments, URLs, filtering, retries, response bounds, and error shapes;
- a loopback integration test using a real MCP stdio child process;
- one controlled CI smoke test that invokes every tool against public data;
- strict TypeScript build, npm package inspection, dependency audit, SBOM, and deterministic ZIP packaging.

The intended deployment is local stdio from an MCP host such as Claude Desktop or Cursor. See `README.md` for configuration examples.
