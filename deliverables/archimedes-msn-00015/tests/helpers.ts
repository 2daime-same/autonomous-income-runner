import http, { type IncomingMessage, type ServerResponse } from 'node:http';

import type { AuthIntent, GitHubTokenProvider } from '../src/types.js';

export interface TestServer {
  baseUrl: string;
  close(): Promise<void>;
}

export async function startTestServer(
  handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>,
): Promise<TestServer> {
  const server = http.createServer((request, response) => {
    Promise.resolve(handler(request, response)).catch((error: unknown) => {
      response.statusCode = 500;
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({ message: error instanceof Error ? error.message : 'test error' }));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Test server did not expose a TCP address.');
  }
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    close: () => new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

export function sendJson(
  response: ServerResponse,
  value: unknown,
  status = 200,
  headers: Record<string, string> = {},
): void {
  response.statusCode = status;
  response.setHeader('content-type', 'application/json');
  response.setHeader('x-github-request-id', 'TEST-REQUEST-ID');
  response.setHeader('x-ratelimit-limit', '5000');
  response.setHeader('x-ratelimit-remaining', '4999');
  response.setHeader('x-ratelimit-used', '1');
  response.setHeader('x-ratelimit-reset', String(Math.floor(Date.now() / 1000) + 3600));
  response.setHeader('x-ratelimit-resource', 'core');
  for (const [name, valueHeader] of Object.entries(headers)) {
    response.setHeader(name, valueHeader);
  }
  response.end(JSON.stringify(value));
}

export function sendText(
  response: ServerResponse,
  value: string,
  status = 200,
  contentType = 'text/plain',
  headers: Record<string, string> = {},
): void {
  response.statusCode = status;
  response.setHeader('content-type', contentType);
  response.setHeader('x-github-request-id', 'TEST-REQUEST-ID');
  for (const [name, valueHeader] of Object.entries(headers)) {
    response.setHeader(name, valueHeader);
  }
  response.end(value);
}

export class StaticTokenProvider implements GitHubTokenProvider {
  readonly mode = 'pat' as const;

  constructor(
    private readonly allowWrites = true,
    private readonly value = 'test-token',
  ) {}

  async token(intent: AuthIntent): Promise<string | null> {
    if (intent === 'write' && !this.allowWrites) {
      throw new Error('writes disabled in test token provider');
    }
    return this.value;
  }

  describe(intent: AuthIntent): string {
    return intent === 'write' && !this.allowWrites ? 'unavailable' : 'test-token';
  }
}

export const SAMPLE_PATCH = [
  '@@ -1,4 +1,5 @@',
  ' const value = 1;',
  '-const oldName = true;',
  '+const newName = true;',
  '+const added = 2;',
  ' return value;',
].join('\n');
