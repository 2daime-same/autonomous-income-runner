import { GitHubApiError } from './errors.js';
import type { JsonObject, JsonValue } from './types.js';

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function asJsonValue(value: unknown): JsonValue {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(asJsonValue);
  }
  if (typeof value === 'object') {
    const output: JsonObject = {};
    for (const [key, item] of Object.entries(value)) {
      if (item !== undefined) {
        output[key] = asJsonValue(item);
      }
    }
    return output;
  }
  return String(value);
}

export function collectionFromPayload(payload: JsonValue, keys: readonly string[]): JsonValue[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (!isJsonObject(payload)) {
    throw new GitHubApiError('invalid_response', 'Public API list response was not an object or array.');
  }
  for (const key of keys) {
    const candidate = payload[key];
    if (Array.isArray(candidate)) {
      return candidate;
    }
    if (isJsonObject(candidate)) {
      for (const nestedKey of ['items', 'results', 'data']) {
        const nested = candidate[nestedKey];
        if (Array.isArray(nested)) {
          return nested;
        }
      }
    }
  }
  throw new GitHubApiError('invalid_response', 'Public API list response contained no supported collection.');
}

export function totalFromPayload(payload: JsonValue, fallback: number): number | null {
  if (!isJsonObject(payload)) {
    return fallback;
  }
  const containers: JsonObject[] = [payload];
  if (isJsonObject(payload.pagination)) {
    containers.push(payload.pagination);
  }
  for (const container of containers) {
    for (const key of ['total', 'total_count', 'count']) {
      const value = container[key];
      if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
        return value;
      }
    }
  }
  return fallback;
}
