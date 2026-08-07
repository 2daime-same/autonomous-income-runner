import process from 'node:process';

const originalFetch = globalThis.fetch.bind(globalThis);
const BLOCKED_PATH = /(?:^|\/)(?:fund|funds|funding|deposit|deposits|checkout|billing|payment|payments|purchase|purchases|buy|stake|staking|bond|bonds|subscribe|subscription|upgrade|top-?up|withdraw|withdrawal|send-funds|transfer|transfers|x402)(?:\/|$|\?|#)/i;
const BLOCKED_BODY = /(?:"(?:action|operation|type|method)"\s*:\s*"(?:fund|deposit|pay|payment|purchase|buy|stake|bond|withdraw|transfer|send|swap|bridge|approve|permit)")/i;
const BLOCKED_RPC = /^(?:eth_sendTransaction|eth_sendRawTransaction|wallet_sendCalls|wallet_sendTransaction|personal_sendTransaction|eth_signTransaction|wallet_addEthereumChain)$/i;

function violation(message) {
  const error = new Error(`ZERO_SPEND_CONSTITUTION: ${message}`);
  error.code = 'ZERO_SPEND_CONSTITUTION';
  throw error;
}

function inspectRpcBody(body) {
  if (typeof body !== 'string' || !body.trim()) return;
  try {
    const payload = JSON.parse(body);
    const calls = Array.isArray(payload) ? payload : [payload];
    for (const call of calls) {
      if (BLOCKED_RPC.test(String(call?.method ?? ''))) {
        violation(`blocked blockchain write method ${call.method}`);
      }
    }
  } catch (error) {
    if (error?.code === 'ZERO_SPEND_CONSTITUTION') throw error;
  }
}

globalThis.fetch = async function zeroSpendFetch(input, init = {}) {
  const url = typeof input === 'string' ? input : String(input?.url ?? input);
  const method = String(init?.method ?? (typeof input === 'object' ? input?.method : 'GET') ?? 'GET').toUpperCase();
  const body = typeof init?.body === 'string' ? init.body : '';

  inspectRpcBody(body);

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    let pathname = '';
    try { pathname = new URL(url).pathname; } catch { pathname = url; }
    if (BLOCKED_PATH.test(pathname)) violation(`blocked financial write ${method} ${pathname}`);
    if (BLOCKED_BODY.test(body)) violation(`blocked financial action in request body for ${method} ${pathname}`);
  }

  return originalFetch(input, init);
};

process.env.ZERO_SPEND_CONSTITUTION = 'ENFORCED';
process.env.MAX_OWNER_ASSET_OUTFLOW = '0';
