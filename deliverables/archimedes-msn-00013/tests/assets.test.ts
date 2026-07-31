import assert from 'node:assert/strict';
import test from 'node:test';

import { assetFromProductHtml, assetIdsFromSitemap } from '../src/assets.js';
import { ArchimedesApiError } from '../src/errors.js';
import { assetHtml, sitemapXml } from './helpers.js';

const BASE_URL = new URL('https://archimedes.market/');
const ASSET_ID = '7665aafa-08ff-4391-a1ef-82ea87ed4002';

test('extracts unique same-origin asset IDs from a sitemap', () => {
  const xml = `${sitemapXml(BASE_URL.href, [ASSET_ID, ASSET_ID])}
    <url><loc>https://example.com/assets/11111111-1111-4111-8111-111111111111</loc></url>
    <url><loc>https://archimedes.market/assets/not-a-uuid</loc></url>`;
  assert.deepEqual(assetIdsFromSitemap(xml, BASE_URL), [ASSET_ID]);
});

test('normalizes public Product JSON-LD without executing page scripts', () => {
  const html = `${assetHtml(BASE_URL.href, {
    id: ASSET_ID,
    title: 'ModelCard — ML Model Card Generator',
    description: 'Python model card generator',
    assetType: 'CODE',
    price: 12,
    license: 'standard',
  })}<script>globalThis.SHOULD_NOT_RUN = true;</script>`;
  const asset = assetFromProductHtml(html, ASSET_ID, BASE_URL);
  assert.equal(asset.id, ASSET_ID);
  assert.equal(asset.title, 'ModelCard — ML Model Card Generator');
  assert.equal(asset.asset_type, 'CODE');
  assert.equal(asset.price, 12);
  assert.equal(asset.license_type, 'standard');
  assert.equal(asset.metadata_source, 'public static schema.org Product JSON-LD');
  assert.equal(globalThis.SHOULD_NOT_RUN, undefined);
});

test('rejects missing or mismatched Product metadata', () => {
  assert.throws(() => assetFromProductHtml('<html></html>', ASSET_ID, BASE_URL), ArchimedesApiError);
  const otherId = '11111111-1111-4111-8111-111111111111';
  assert.throws(
    () => assetFromProductHtml(assetHtml(BASE_URL.href, { id: otherId, title: 'Other' }), ASSET_ID, BASE_URL),
    /did not match the requested asset/,
  );
});
