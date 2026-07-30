import {writeFile, mkdir, rename} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const output = process.env.AGENTJOB_MCP_TOOLS_OUTPUT ?? 'market-output/agentjob-mcp-tools.json';
const endpoint = 'https://agent-job.ai/api/mcp';

function sanitize(value) {
  if (Array.isArray(value)) {
    return value.map(sanitize);
  }

  if (value && typeof value === 'object') {
    const result = {};
    for (const [key, item] of Object.entries(value)) {
      if (/token|secret|api.?key|authorization|private/i.test(key)) {
        result[key] = '[REDACTED]';
      } else {
        result[key] = sanitize(item);
      }
    }
    return result;
  }

  if (typeof value === 'string') {
    return value.replace(/\b(?:ak|aj|agentjob)_[A-Za-z0-9_-]{8,}/gi, '[REDACTED]');
  }

  return value;
}

const client = new Client({name: 'nexaworks-agentjob-schema-probe', version: '1.0.0'});
const transport = new StreamableHTTPClientTransport(new URL(endpoint));
let result;
try {
  await client.connect(transport);
  const response = await client.listTools();
  result = {
    generated_at: new Date().toISOString(),
    endpoint,
    connected_without_authentication: true,
    tool_count: response.tools.length,
    tools: sanitize(response.tools),
    calls_performed: ['initialize', 'tools/list'],
    mutating_tool_called: false,
  };
} catch (error) {
  result = {
    generated_at: new Date().toISOString(),
    endpoint,
    connected_without_authentication: false,
    error: `${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`.slice(0, 3000),
    calls_performed: ['initialize', 'tools/list'],
    mutating_tool_called: false,
  };
  process.exitCode = 1;
} finally {
  try {
    await client.close();
  } catch {}
}

await mkdir(path.dirname(output), {recursive: true});
const temporary = `${output}.tmp`;
await writeFile(temporary, `${JSON.stringify(result, null, 2)}\n`, {mode: 0o600});
await rename(temporary, output);
console.log(JSON.stringify({ok: result.connected_without_authentication, tool_count: result.tool_count ?? 0}));