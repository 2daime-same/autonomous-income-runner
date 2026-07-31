import { localFilter } from './filter.js';
import { PublicJsonHttpClient } from './http.js';
import { collectionFromPayload, isJsonObject, totalFromPayload } from './json.js';
import type {
  ArchimedesClientOptions,
  JsonObject,
  JsonValue,
  PublicDetailResult,
  PublicSearchResult,
  SearchAssetsInput,
  SearchBountiesInput,
} from './types.js';
import { boundedInteger, optionalText, publicIdentifier } from './validation.js';

function isFunded(item: JsonValue): boolean {
  if (!isJsonObject(item)) {
    return false;
  }
  if (item.is_funded === true || item.funded === true) {
    return true;
  }
  for (const key of ['escrow_status', 'funding_status', 'payment_status']) {
    const value = item[key];
    if (typeof value === 'string' && ['locked', 'funded', 'secured', 'paid'].includes(value.toLowerCase())) {
      return true;
    }
  }
  return false;
}

function queryObject(entries: ReadonlyArray<readonly [string, JsonValue | undefined]>): JsonObject {
  const result: JsonObject = {};
  for (const [key, value] of entries) {
    if (value !== undefined) {
      result[key] = value;
    }
  }
  return result;
}

export class ArchimedesPublicClient {
  private readonly http: PublicJsonHttpClient;
  private readonly now: () => Date;

  constructor(options: ArchimedesClientOptions = {}) {
    this.http = new PublicJsonHttpClient(options);
    this.now = options.now ?? (() => new Date());
  }

  async searchAssets(input: SearchAssetsInput = {}): Promise<PublicSearchResult> {
    const query = optionalText(input.query, 'query', 200);
    const assetType = optionalText(input.asset_type, 'asset_type', 80);
    const limit = boundedInteger(input.limit, 20, 1, 50);
    const offset = boundedInteger(input.offset, 0, 0, 10_000);

    const payload = await this.http.get('api/public/assets', { limit, offset });
    const upstreamItems = collectionFromPayload(payload, ['items', 'assets', 'results', 'data']);
    const items = localFilter(upstreamItems, [query, assetType]);

    return {
      source: 'archimedes.market',
      resource: 'assets',
      query: queryObject([
        ['query', query],
        ['asset_type', assetType],
        ['limit', limit],
        ['offset', offset],
      ]),
      returned: items.length,
      total: totalFromPayload(payload, upstreamItems.length),
      items,
      fetched_at: this.now().toISOString(),
    };
  }

  async getAsset(assetId: string): Promise<PublicDetailResult> {
    const id = publicIdentifier(assetId, 'asset_id');
    const item = await this.http.get(`api/public/assets/${encodeURIComponent(id)}`);
    return {
      source: 'archimedes.market',
      resource: 'asset',
      id,
      item,
      fetched_at: this.now().toISOString(),
    };
  }

  async searchBounties(input: SearchBountiesInput = {}): Promise<PublicSearchResult> {
    const query = optionalText(input.query, 'query', 200);
    const status = optionalText(input.status, 'status', 40) ?? 'open';
    const category = optionalText(input.category, 'category', 80);
    const fundedOnly = input.funded_only ?? true;
    const limit = boundedInteger(input.limit, 20, 1, 50);
    const offset = boundedInteger(input.offset, 0, 0, 10_000);

    const payload = await this.http.get('api/public/bounties', { status, limit, offset });
    const upstreamItems = collectionFromPayload(payload, ['items', 'bounties', 'results', 'data']);
    const textFiltered = localFilter(upstreamItems, [query, category]);
    const items = fundedOnly ? textFiltered.filter(isFunded) : textFiltered;

    return {
      source: 'archimedes.market',
      resource: 'bounties',
      query: queryObject([
        ['query', query],
        ['status', status],
        ['category', category],
        ['funded_only', fundedOnly],
        ['limit', limit],
        ['offset', offset],
      ]),
      returned: items.length,
      total: totalFromPayload(payload, upstreamItems.length),
      items,
      fetched_at: this.now().toISOString(),
    };
  }

  async getBounty(bountyId: string): Promise<PublicDetailResult> {
    const id = publicIdentifier(bountyId, 'bounty_id');
    const item = await this.http.get(`api/public/bounties/${encodeURIComponent(id)}`);
    return {
      source: 'archimedes.market',
      resource: 'bounty',
      id,
      item,
      fetched_at: this.now().toISOString(),
    };
  }
}
