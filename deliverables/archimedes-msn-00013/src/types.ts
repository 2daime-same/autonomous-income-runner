export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface SearchAssetsInput {
  query?: string | undefined;
  asset_type?: string | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}

export interface SearchBountiesInput {
  query?: string | undefined;
  status?: string | undefined;
  category?: string | undefined;
  funded_only?: boolean | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}

export interface PublicSearchResult {
  source: 'archimedes.market';
  resource: 'assets' | 'bounties';
  query: JsonObject;
  returned: number;
  total: number | null;
  items: JsonValue[];
  fetched_at: string;
}

export interface PublicDetailResult {
  source: 'archimedes.market';
  resource: 'asset' | 'bounty';
  id: string;
  item: JsonValue;
  fetched_at: string;
}

export interface ArchimedesClientOptions {
  baseUrl?: string;
  timeoutMs?: number;
  maxResponseBytes?: number;
  maxRetries?: number;
  userAgent?: string;
  fetchImpl?: typeof fetch;
  sleep?: (milliseconds: number) => Promise<void>;
  now?: () => Date;
  assetCatalogTtlMs?: number;
  assetScanConcurrency?: number;
  assetScanLimit?: number;
}
