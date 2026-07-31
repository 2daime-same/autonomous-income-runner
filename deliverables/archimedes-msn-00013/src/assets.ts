import { ArchimedesApiError } from './errors.js';
import { asJsonValue } from './json.js';
import type { JsonObject, JsonValue } from './types.js';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|quot|apos|amp|lt|gt);/gi, (_match, entity: string) => {
    const normalized = entity.toLowerCase();
    if (normalized === 'quot') return '"';
    if (normalized === 'apos') return "'";
    if (normalized === 'amp') return '&';
    if (normalized === 'lt') return '<';
    if (normalized === 'gt') return '>';
    const radix = normalized.startsWith('#x') ? 16 : 10;
    const digits = normalized.slice(radix === 16 ? 2 : 1);
    const codePoint = Number.parseInt(digits, radix);
    if (!Number.isFinite(codePoint) || codePoint < 0 || codePoint > 0x10ffff) {
      return _match;
    }
    try {
      return String.fromCodePoint(codePoint);
    } catch {
      return _match;
    }
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringField(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function firstRecord(value: unknown): Record<string, unknown> | null {
  if (isRecord(value)) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.find(isRecord) ?? null;
  }
  return null;
}

function hasProductType(value: unknown): boolean {
  if (typeof value === 'string') {
    return value.toLowerCase() === 'product';
  }
  return Array.isArray(value) && value.some((item) => typeof item === 'string' && item.toLowerCase() === 'product');
}

function productCandidates(value: unknown): Record<string, unknown>[] {
  const output: Record<string, unknown>[] = [];
  const visit = (candidate: unknown): void => {
    if (Array.isArray(candidate)) {
      for (const item of candidate) visit(item);
      return;
    }
    if (!isRecord(candidate)) return;
    if (hasProductType(candidate['@type'])) output.push(candidate);
    const graph = candidate['@graph'];
    if (Array.isArray(graph)) visit(graph);
  };
  visit(value);
  return output;
}

function imageValue(value: unknown): JsonValue {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    const first = value.find((item) => typeof item === 'string' || isRecord(item));
    return first === undefined ? null : imageValue(first);
  }
  if (isRecord(value)) {
    return stringField(value.url) ?? stringField(value.contentUrl) ?? null;
  }
  return null;
}

function licenseValue(value: unknown): string | null {
  const properties = Array.isArray(value) ? value : [value];
  for (const property of properties) {
    if (!isRecord(property)) continue;
    const name = stringField(property.name);
    if (name?.toLowerCase() !== 'license') continue;
    const license = stringField(property.value);
    if (license) return license;
  }
  return null;
}

function normalizedAssetPath(baseUrl: URL, assetId: string): string {
  return new URL(`assets/${assetId}`, baseUrl).pathname.replace(/\/$/, '');
}

export function assetIdsFromSitemap(xml: string, baseUrl: URL, maxAssets = 500): string[] {
  if (!Number.isSafeInteger(maxAssets) || maxAssets < 1 || maxAssets > 5_000) {
    throw new ArchimedesApiError('invalid_configuration', 'maxAssets must be between 1 and 5000.');
  }
  const assetRoot = new URL('assets/', baseUrl).pathname.replace(/\/$/, '');
  const ids = new Set<string>();
  const locations = /<loc>\s*([^<]+?)\s*<\/loc>/gi;
  for (const match of xml.matchAll(locations)) {
    const rawLocation = match[1];
    if (!rawLocation) continue;
    let location: URL;
    try {
      location = new URL(decodeEntities(rawLocation.trim()), baseUrl);
    } catch {
      continue;
    }
    if (location.origin !== baseUrl.origin || location.search || location.hash) continue;
    const prefix = `${assetRoot}/`;
    if (!location.pathname.startsWith(prefix)) continue;
    const remainder = location.pathname.slice(prefix.length).replace(/\/$/, '');
    if (!UUID_PATTERN.test(remainder) || remainder.includes('/')) continue;
    ids.add(remainder.toLowerCase());
    if (ids.size > maxAssets) {
      throw new ArchimedesApiError(
        'catalog_too_large',
        `Public sitemap contained more than the configured ${maxAssets} asset limit.`,
      );
    }
  }
  if (ids.size === 0) {
    throw new ArchimedesApiError('invalid_response', 'Public sitemap contained no valid asset detail URLs.');
  }
  return [...ids];
}

export function assetFromProductHtml(html: string, assetId: string, baseUrl: URL): JsonObject {
  const expectedPath = normalizedAssetPath(baseUrl, assetId);
  const candidates: Record<string, unknown>[] = [];
  const scripts = /<script\b(?=[^>]*\btype\s*=\s*["']application\/ld\+json["'])[^>]*>([\s\S]*?)<\/script>/gi;
  for (const match of html.matchAll(scripts)) {
    const body = match[1];
    if (!body?.trim()) continue;
    try {
      candidates.push(...productCandidates(JSON.parse(decodeEntities(body.trim())) as unknown));
    } catch {
      continue;
    }
  }
  if (candidates.length === 0) {
    throw new ArchimedesApiError(
      'invalid_response',
      'Public asset detail page contained no valid schema.org Product JSON-LD.',
    );
  }

  const matching = candidates.find((candidate) => {
    const url = stringField(candidate.url);
    if (!url) return false;
    try {
      const parsed = new URL(url, baseUrl);
      return parsed.origin === baseUrl.origin && parsed.pathname.replace(/\/$/, '') === expectedPath;
    } catch {
      return false;
    }
  });
  const product = matching ?? candidates[0];
  if (!product) {
    throw new ArchimedesApiError('invalid_response', 'Public asset Product metadata could not be selected.');
  }

  const title = stringField(product.name);
  if (!title) {
    throw new ArchimedesApiError('invalid_response', 'Public asset Product metadata contained no name.');
  }
  const productUrl = stringField(product.url);
  if (productUrl) {
    let parsed: URL;
    try {
      parsed = new URL(productUrl, baseUrl);
    } catch (error) {
      throw new ArchimedesApiError('invalid_response', 'Public asset Product URL was invalid.', { cause: error });
    }
    if (parsed.origin !== baseUrl.origin || parsed.pathname.replace(/\/$/, '') !== expectedPath) {
      throw new ArchimedesApiError('invalid_response', 'Public asset Product URL did not match the requested asset.');
    }
  }

  const offers = firstRecord(product.offers);
  const rawPrice = offers?.price;
  const price: JsonValue =
    typeof rawPrice === 'number' && Number.isFinite(rawPrice)
      ? rawPrice
      : typeof rawPrice === 'string' && rawPrice.trim()
        ? rawPrice.trim()
        : null;
  const publicUrl = new URL(`assets/${assetId}`, baseUrl).href;

  return {
    id: assetId,
    title,
    description: stringField(product.description),
    asset_type: stringField(product.category),
    price,
    currency: stringField(offers?.priceCurrency),
    availability: stringField(offers?.availability),
    license_type: licenseValue(product.additionalProperty),
    image: imageValue(product.image),
    public_url: publicUrl,
    metadata_source: 'public static schema.org Product JSON-LD',
    schema_org_product: asJsonValue(product),
  };
}
