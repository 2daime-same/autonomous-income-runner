#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { ArchimedesPublicClient } from './client.js';
import { optionsFromEnvironment } from './config.js';
import { createMcpServer } from './server.js';

async function main(): Promise<void> {
  const client = new ArchimedesPublicClient(optionsFromEnvironment());
  const server = createMcpServer(client);
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : 'Unknown startup failure.';
  console.error(`archimedes-market-mcp failed to start: ${message}`);
  process.exitCode = 1;
});
