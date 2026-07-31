export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface SearchAssetsInput {
  query?: string;
  asset_type?: string;
  limit?: number;
  offset?: number;
}

export interface SearchBountiesInput {
  query?: string;
  status?: string;
  category?: string;
  funded_only?: boolean;
  limit?: number;
  offset?: number;
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
}
