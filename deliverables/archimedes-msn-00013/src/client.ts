import { assetFromProductHtml, assetIdsFromSitemap } from './assets.js';
import { ArchimedesApiError } from './errors.js';
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
import { boundedInteger, normalizeBaseUrl, optionalText, publicIdentifier } from './validation.js';

interface TimedValue<T> {
  expiresAt: number;
  value: T;
}

async function concurrentMap<T>(
  items: readonly string[],
  concurrency: number,
  operation: (item: string, index: number) => Promise<T>,
): Promise<T[]> {
  const results: Array<T | undefined> = new Array(items.length);
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(concurrency, Math.max(items.length, 1)) }, async () => {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= items.length) return;
      const item = items[index];
      if (item === undefined) return;
      results[index] = await operation(item, index);
    }
  });
  await Promise.all(workers);
  return results.filter((item): item is T => item !== undefined);
}

function integerOption(value: number | undefined, fallback: number, minimum: number, maximum: number, name: string): number {
  const selected = value ?? fallback;
  if (!Number.isSafeInteger(selected) || selected < minimum || selected > maximum) {
    throw new ArchimedesApiError(
      'invalid_configuration',
      `${name} must be an integer between ${minimum} and ${maximum}.`,
    );
  }
  return selected;
}

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

function assetTypeMatches(item: JsonValue, assetType: string | undefined): boolean {
  if (!assetType) return true;
  if (!isJsonObject(item)) return false;
  const value = item.asset_type;
  return typeof value === 'string' && value.toLocaleLowerCase('en-US') === assetType.toLocaleLowerCase('en-US');
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
  private readonly baseUrl: URL;
  private readonly now: () => Date;
  private readonly assetCatalogTtlMs: number;
  private readonly assetScanConcurrency: number;
  private readonly assetScanLimit: number;
  private assetIdsCache: TimedValue<string[]> | null = null;
  private assetCatalogCache: TimedValue<JsonObject[]> | null = null;
  private assetCatalogPromise: Promise<JsonObject[]> | null = null;
  private readonly assetDetailCache = new Map<string, TimedValue<JsonObject>>();

  constructor(options: ArchimedesClientOptions = {}) {
    this.http = new PublicJsonHttpClient(options);
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? 'https://archimedes.market');
    this.now = options.now ?? (() => new Date());
    this.assetCatalogTtlMs = integerOption(
      options.assetCatalogTtlMs,
      15 * 60 * 1_000,
      0,
      24 * 60 * 60 * 1_000,
      'assetCatalogTtlMs',
    );
    this.assetScanConcurrency = integerOption(options.assetScanConcurrency, 4, 1, 8, 'assetScanConcurrency');
    this.assetScanLimit = integerOption(options.assetScanLimit, 500, 1, 5_000, 'assetScanLimit');
  }

  async searchAssets(input: SearchAssetsInput = {}): Promise<PublicSearchResult> {
    const query = optionalText(input.query, 'query', 200);
    const assetType = optionalText(input.asset_type, 'asset_type', 80);
    const limit = boundedInteger(input.limit, 20, 1, 50);
    const offset = boundedInteger(input.offset, 0, 0, 10_000);

    let items: JsonValue[];
    let total: number;
    const cachedCatalog = this.freshValue(this.assetCatalogCache);
    if (query !== undefined || assetType !== undefined || cachedCatalog !== null) {
      const catalog = cachedCatalog ?? (await this.loadAssetCatalog());
      const filtered = localFilter(catalog, [query]).filter((item) => assetTypeMatches(item, assetType));
      total = filtered.length;
      items = filtered.slice(offset, offset + limit);
    } else {
      const ids = await this.loadAssetIds();
      total = ids.length;
      const selected = ids.slice(offset, offset + limit);
      const records = await concurrentMap(selected, this.assetScanConcurrency, async (id) =>
        this.fetchAssetRecordOrNull(id),
      );
      items = records.filter((item): item is JsonObject => item !== null);
    }

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
      total,
      items,
      fetched_at: this.now().toISOString(),
    };
  }

  async getAsset(assetId: string): Promise<PublicDetailResult> {
    const id = publicIdentifier(assetId, 'asset_id');
    const item = await this.fetchAssetRecord(id);
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

  private freshValue<T>(entry: TimedValue<T> | null): T | null {
    return entry !== null && entry.expiresAt > this.now().getTime() ? entry.value : null;
  }

  private expiry(): number {
    return this.now().getTime() + this.assetCatalogTtlMs;
  }

  private async loadAssetIds(): Promise<string[]> {
    const cached = this.freshValue(this.assetIdsCache);
    if (cached !== null) return cached;
    const sitemap = await this.http.getText('sitemap.xml', {}, 'application/xml, text/xml;q=0.9, text/plain;q=0.5');
    const ids = assetIdsFromSitemap(sitemap, this.baseUrl, this.assetScanLimit);
    this.assetIdsCache = { value: ids, expiresAt: this.expiry() };
    return ids;
  }

  private async fetchAssetRecord(assetId: string): Promise<JsonObject> {
    const cached = this.freshValue(this.assetDetailCache.get(assetId) ?? null);
    if (cached !== null) return cached;
    const html = await this.http.getText(
      `assets/${encodeURIComponent(assetId)}`,
      {},
      'text/html, application/xhtml+xml;q=0.9',
    );
    const item = assetFromProductHtml(html, assetId, this.baseUrl);
    this.assetDetailCache.set(assetId, { value: item, expiresAt: this.expiry() });
    return item;
  }

  private async fetchAssetRecordOrNull(assetId: string): Promise<JsonObject | null> {
    try {
      return await this.fetchAssetRecord(assetId);
    } catch (error) {
      if (
        error instanceof ArchimedesApiError &&
        (error.code === 'not_found' || error.code === 'invalid_response')
      ) {
        return null;
      }
      throw error;
    }
  }

  private async loadAssetCatalog(): Promise<JsonObject[]> {
    const cached = this.freshValue(this.assetCatalogCache);
    if (cached !== null) return cached;
    if (this.assetCatalogPromise !== null) return this.assetCatalogPromise;

    const promise = (async (): Promise<JsonObject[]> => {
      const ids = await this.loadAssetIds();
      const records = await concurrentMap(ids, this.assetScanConcurrency, async (id) =>
        this.fetchAssetRecordOrNull(id),
      );
      const catalog = records.filter((item): item is JsonObject => item !== null);
      if (catalog.length === 0) {
        throw new ArchimedesApiError(
          'invalid_response',
          'Public sitemap assets yielded no readable Product metadata.',
        );
      }
      this.assetCatalogCache = { value: catalog, expiresAt: this.expiry() };
      return catalog;
    })();
    this.assetCatalogPromise = promise;
    try {
      return await promise;
    } finally {
      if (this.assetCatalogPromise === promise) {
        this.assetCatalogPromise = null;
      }
    }
  }
}
