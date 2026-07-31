import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';

export interface TestServer {
  baseUrl: string;
  close: () => Promise<void>;
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
  const body = JSON.stringify(value);
  response.statusCode = status;
  response.setHeader('content-type', 'application/json');
  response.setHeader('content-length', String(Buffer.byteLength(body)));
  response.end(body);
}
