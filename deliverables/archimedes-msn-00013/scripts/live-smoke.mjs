import { ArchimedesPublicClient } from '../dist/client.js';
import { optionsFromEnvironment } from '../dist/config.js';

function publicId(item) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) {
    return null;
  }
  for (const key of ['id', 'asset_id', 'bounty_id']) {
    const value = item[key];
    if (typeof value === 'string' && /^[A-Za-z0-9_-]{8,128}$/.test(value)) {
      return value;
    }
  }
  return null;
}

async function firstAsset(client) {
  const python = await client.searchAssets({ query: 'Python', limit: 50, offset: 0 });
  const selected = python.items.find((item) => publicId(item));
  if (selected) {
    return { search: python, id: publicId(selected) };
  }
  const fallback = await client.searchAssets({ limit: 50, offset: 0 });
  const fallbackItem = fallback.items.find((item) => publicId(item));
  return { search: python, id: fallbackItem ? publicId(fallbackItem) : null };
}

async function firstBounty(client) {
  const mcp = await client.searchBounties({ query: 'MCP', funded_only: true, limit: 50, offset: 0 });
  const selected = mcp.items.find((item) => publicId(item));
  if (selected) {
    return { search: mcp, id: publicId(selected) };
  }
  const fallback = await client.searchBounties({ funded_only: false, limit: 50, offset: 0 });
  const fallbackItem = fallback.items.find((item) => publicId(item));
  return { search: mcp, id: fallbackItem ? publicId(fallbackItem) : null };
}

const client = new ArchimedesPublicClient(optionsFromEnvironment());
const assetCandidate = await firstAsset(client);
if (!assetCandidate.id) {
  throw new Error('The public asset directory returned no usable asset ID.');
}
const asset = await client.getAsset(assetCandidate.id);

const bountyCandidate = await firstBounty(client);
if (!bountyCandidate.id) {
  throw new Error('The public bounty directory returned no usable bounty ID.');
}
const bounty = await client.getBounty(bountyCandidate.id);

console.log(
  JSON.stringify(
    {
      performed_at: new Date().toISOString(),
      transport: 'public HTTPS GET only',
      authenticated: false,
      operations: [
        {
          tool: 'search_assets',
          query: 'Python',
          returned: assetCandidate.search.returned,
          selected_public_id: assetCandidate.id,
        },
        { tool: 'get_asset', selected_public_id: asset.id, resource: asset.resource },
        {
          tool: 'search_bounties',
          query: 'MCP',
          returned: bountyCandidate.search.returned,
          selected_public_id: bountyCandidate.id,
        },
        { tool: 'get_bounty', selected_public_id: bounty.id, resource: bounty.resource },
      ],
    },
    null,
    2,
  ),
);
