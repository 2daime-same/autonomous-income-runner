import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';

export interface TestServer {
  baseUrl: string;
  close: () => Promise<void>;
}

export interface AssetFixture {
  id: string;
  title: string;
  description?: string;
  assetType?: string;
  price?: number;
  currency?: string;
  license?: string;
}

export async function startTestServer(
  handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>,
): Promise<TestServer> {
  const server = createServer((request, response) => {
    Promise.resolve(handler(request, response)).catch((error: unknown) => {
      response.statusCode = 500;
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({ error: error instanceof Error ? error.message : 'test server error' }));
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.off('error', reject);
      resolve();
    });
  });
  const address = server.address() as AddressInfo;
  return {
    baseUrl: `http://127.0.0.1:${address.port}/`,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
}

export function sendJson(response: ServerResponse, value: unknown, status = 200): void {
  sendText(response, JSON.stringify(value), 'application/json', status);
}

export function sendText(response: ServerResponse, body: string, contentType = 'text/plain', status = 200): void {
  response.statusCode = status;
  response.setHeader('content-type', contentType);
  response.setHeader('content-length', String(Buffer.byteLength(body)));
  response.end(body);
}

export function sitemapXml(baseUrl: string, assetIds: readonly string[]): string {
  const locations = assetIds
    .map((id) => `<url><loc>${new URL(`assets/${id}`, baseUrl).href}</loc></url>`)
    .join('');
  return `<?xml version="1.0" encoding="UTF-8"?><urlset>${locations}</urlset>`;
}

export function assetHtml(baseUrl: string, fixture: AssetFixture): string {
  const product = {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: fixture.title,
    description: fixture.description ?? `${fixture.title} description`,
    url: new URL(`assets/${fixture.id}`, baseUrl).href,
    image: new URL(`images/${fixture.id}.png`, baseUrl).href,
    category: fixture.assetType ?? 'CODE',
    offers: {
      '@type': 'Offer',
      price: fixture.price ?? 12,
      priceCurrency: fixture.currency ?? 'USD',
      availability: 'https://schema.org/InStock',
      url: new URL(`assets/${fixture.id}`, baseUrl).href,
    },
    additionalProperty: {
      '@type': 'PropertyValue',
      name: 'License',
      value: fixture.license ?? 'standard',
    },
  };
  return `<!doctype html><html><head><script type="application/ld+json">${JSON.stringify(product)}</script></head><body><div>Loading asset...</div></body></html>`;
}
