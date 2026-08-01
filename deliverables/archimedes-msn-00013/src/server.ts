import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod/v4';

import { ArchimedesPublicClient } from './client.js';
import { runTool } from './tools.js';
import { VERSION } from './version.js';

const READ_ONLY_ANNOTATIONS = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: true,
} as const;

const searchAssetsSchema = z
  .object({
    query: z.string().trim().max(200).optional().describe('Free-text search, for example Python.'),
    asset_type: z.string().trim().max(80).optional().describe('Optional asset type filter.'),
    limit: z.number().int().min(1).max(50).optional().describe('Maximum page size; defaults to 20.'),
    offset: z.number().int().min(0).max(10_000).optional().describe('Pagination offset; defaults to 0.'),
  })
  .strict();

const getAssetSchema = z
  .object({
    asset_id: z
      .string()
      .trim()
      .min(8)
      .max(128)
      .regex(/^[A-Za-z0-9_-]+$/)
      .describe('Public Archimedes asset identifier.'),
  })
  .strict();

const searchBountiesSchema = z
  .object({
    query: z.string().trim().max(200).optional().describe('Free-text bounty search, for example MCP.'),
    status: z.string().trim().max(40).optional().describe('Bounty status; defaults to open.'),
    category: z.string().trim().max(80).optional().describe('Optional category filter.'),
    funded_only: z.boolean().optional().describe('Return only funded/escrowed work; defaults to true.'),
    limit: z.number().int().min(1).max(50).optional().describe('Maximum page size; defaults to 20.'),
    offset: z.number().int().min(0).max(10_000).optional().describe('Pagination offset; defaults to 0.'),
  })
  .strict();

const getBountySchema = z
  .object({
    bounty_id: z
      .string()
      .trim()
      .min(8)
      .max(128)
      .regex(/^[A-Za-z0-9_-]+$/)
      .describe('Public Archimedes bounty identifier.'),
  })
  .strict();

export function createMcpServer(client: ArchimedesPublicClient = new ArchimedesPublicClient()): McpServer {
  const server = new McpServer({
    name: 'archimedes-market-mcp',
    version: VERSION,
  });

  server.registerTool(
    'search_assets',
    {
      title: 'Search Archimedes Assets',
      description:
        'Search public engineering assets on Archimedes Market. This tool is read-only and uses no account or API credential.',
      inputSchema: searchAssetsSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.searchAssets(input)),
  );

  server.registerTool(
    'get_asset',
    {
      title: 'Get Archimedes Asset',
      description:
        'Fetch public metadata for one Archimedes Market asset identifier. This tool performs one unauthenticated GET request.',
      inputSchema: getAssetSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async ({ asset_id: assetId }) => runTool(async () => client.getAsset(assetId)),
  );

  server.registerTool(
    'search_bounties',
    {
      title: 'Search Archimedes Bounties',
      description:
        'Search public Archimedes Market bounties. It defaults to open, funded work and does not claim, accept, or submit anything.',
      inputSchema: searchBountiesSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async (input) => runTool(async () => client.searchBounties(input)),
  );

  server.registerTool(
    'get_bounty',
    {
      title: 'Get Archimedes Bounty',
      description:
        'Fetch public requirements, deliverables, and acceptance-test metadata for one Archimedes bounty identifier.',
      inputSchema: getBountySchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async ({ bounty_id: bountyId }) => runTool(async () => client.getBounty(bountyId)),
  );

  return server;
}
