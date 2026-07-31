# MSN-00013 requirements conflict

The public mission snapshot contains two incompatible implementation directions:

- one section requests Python, TensorFlow, Flask, and AWS/Azure;
- the code deliverable, npm entrypoint, TypeScript SDK requirement, and automated acceptance tests request a TypeScript MCP server with four named tools.

This candidate follows the directly testable TypeScript path:

1. `@modelcontextprotocol/sdk` over stdio;
2. `npm start` and a local executable entrypoint;
3. `search_assets`, `get_asset`, `search_bounties`, and `get_bounty`;
4. public read-only API access;
5. Markdown documentation and automated tests.

A separate cloud/TensorFlow service would not contribute to those four metadata tools. Platform support has been asked which requirement set is authoritative. Until written clarification or platform acceptance exists, this file is traceability rather than a claim that any requirement is waived.
