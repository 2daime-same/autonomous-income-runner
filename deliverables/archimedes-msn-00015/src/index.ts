#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { GitHubPullRequestClient } from './client.js';
import { optionsFromEnvironment } from './config.js';
import { createMcpServer } from './server.js';

async function main(): Promise<void> {
  const client = new GitHubPullRequestClient(optionsFromEnvironment());
  const server = createMcpServer(client);
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(() => {
  process.stderr.write('archimedes-github-pr-mcp failed to start.\n');
  process.exitCode = 1;
});
