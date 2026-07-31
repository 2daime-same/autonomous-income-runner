# Agentic Gateway -- Agent Skill

## What This Is

A crypto-native API marketplace where AI agents deposit USDC once, then search and call any API instantly using wallet signatures. Automatic refunds if an API fails.

## Base URL

`https://api.agenticgateway.io` (or your self-hosted instance)

## Quick Start

```
1. GET  /v1/deposit-address          → send USDC to the returned vault address (Base L2 or Solana)
2. GET  /v1/tools/search?query=...   → find a tool by keyword or intent
3. POST /v1/proxy/:toolId            → call the tool (signed request) → get the result
```

### Alternative: Pay per Request with x402

No deposit needed. Send a request without auth headers and the gateway returns HTTP 402 with x402 payment requirements. Sign the USDC payment, retry with a `PAYMENT-SIGNATURE` header, and the request is processed. Two integration methods are available -- see the full x402 section below.

```
1. POST /v1/proxy/:toolId            → receive 402 with payment requirements
2. Sign USDC payment authorization   → create PAYMENT-SIGNATURE (Base64)
3. POST /v1/proxy/:toolId            → retry with PAYMENT-SIGNATURE header → get the result
```

## Payment Methods

The gateway supports two payment methods. Choose whichever suits your use case.

| Method | How It Works | Best For |
|---|---|---|
| **Balance** (default) | Deposit USDC/USDT once, pay from platform balance per request | High-volume agents, lowest per-call cost |
| **x402** (pay-per-request) | Pay on-chain via x402 protocol each request (Base L2 or Solana), no deposit needed | One-off calls, zero-trust agents, no setup |

If x402 is enabled, tools include `x402_supported: true` in their listing.

## Authentication (Balance Mode)

Authenticated endpoints require two headers:

| Header | Value |
|---|---|
| `X-Timestamp` | `Date.now().toString()` (Unix milliseconds) |
| `X-Signature` | `ethers.signMessage(timestamp + keccak256(JSON.stringify(body)))` |

The timestamp must be within 5 minutes of server time. The recovered wallet address is your identity -- no API keys needed.

### Balance Signing Example (ethers.js v6)

```javascript
import { Wallet, keccak256, toUtf8Bytes } from 'ethers';

const wallet = new Wallet(PRIVATE_KEY);
const body = JSON.stringify({ city: 'London' });
const timestamp = Date.now().toString();
const message = timestamp + keccak256(toUtf8Bytes(body));
const signature = await wallet.signMessage(message);

// Send with headers: X-Timestamp: <timestamp>, X-Signature: <signature>
```

## x402 Pay-Per-Request (No Deposit Needed)

No deposit or pre-authentication required. The gateway follows the [x402 protocol](https://www.x402.org/) (v2). When you POST to `/v1/proxy/:toolId` without auth headers, the gateway returns HTTP 402 with payment details for each supported network. Your agent picks a network (Base L2 or Solana), signs a USDC transfer authorization, and retries with a `PAYMENT-SIGNATURE` header. The gateway verifies the signature, settles the payment on-chain, then proxies to the supplier.

If an API call fails after x402 payment, the refund is credited to your platform balance (usable for future calls via balance mode).

### 402 Response Format

The 402 response body (and `PAYMENT-REQUIRED` header, Base64-encoded) contains:

```json
{
  "x402Version": 2,
  "resource": {
    "url": "https://api.agenticgateway.io/v1/proxy/<toolId>",
    "description": "API call to tool <toolId>",
    "mimeType": "application/json"
  },
  "accepts": [
    {
      "scheme": "exact",
      "network": "eip155:8453",
      "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      "amount": "50000",
      "payTo": "0x..."
    },
    {
      "scheme": "exact",
      "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
      "asset": "USDC",
      "amount": "50000",
      "payTo": "..."
    }
  ]
}
```

Key fields in each `accepts` entry:

| Field | Meaning |
|---|---|
| `scheme` | Always `"exact"` -- pay the exact USDC amount |
| `network` | CAIP-2 chain ID (`eip155:8453` = Base L2, `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` = Solana mainnet) |
| `asset` | USDC contract address (EVM) or `"USDC"` (Solana) |
| `amount` | Cost in USDC smallest units (e.g. `"50000"` = $0.05 USDC with 6 decimals) |
| `payTo` | Wallet address to pay |

### Method 1: Native Fetch (viem + fetch, no x402 packages)

Use only `viem` for wallet signing and standard `fetch` for HTTP. No `@x402/*` packages required. This is useful when you cannot install additional dependencies or want full control over the payment flow.

**Dependencies:** `npm install viem`

```javascript
import { privateKeyToAccount } from "viem/accounts";
import { toHex } from "viem";

const PRIVATE_KEY = "0x...";
const account = privateKeyToAccount(PRIVATE_KEY);

const toolUrl = "https://api.agenticgateway.io/v1/proxy/<toolId>";
const requestBody = JSON.stringify({ city: "London" });

// --- Step 1: Request → receive 402 challenge ---
const res402 = await fetch(toolUrl, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: requestBody,
});

if (res402.status !== 402) {
  throw new Error(`Expected 402, got ${res402.status}`);
}
const paymentRequired = await res402.json();

// --- Step 2: Pick a network and sign the USDC authorization ---
const accept = paymentRequired.accepts.find(
  (a) => a.network === "eip155:8453"
);
if (!accept) throw new Error("No Base L2 payment option available");

const nonce = toHex(crypto.getRandomValues(new Uint8Array(32)));
const validBefore = Math.floor(Date.now() / 1000) + 3600; // 1 hour

// EIP-3009 transferWithAuthorization signed via EIP-712
const signature = await account.signTypedData({
  domain: {
    name: "USD Coin",
    version: "2",
    chainId: 8453,
    verifyingContract: accept.asset,
  },
  types: {
    TransferWithAuthorization: [
      { name: "from", type: "address" },
      { name: "to", type: "address" },
      { name: "value", type: "uint256" },
      { name: "validAfter", type: "uint256" },
      { name: "validBefore", type: "uint256" },
      { name: "nonce", type: "bytes32" },
    ],
  },
  primaryType: "TransferWithAuthorization",
  message: {
    from: account.address,
    to: accept.payTo,
    value: BigInt(accept.amount),
    validAfter: 0n,
    validBefore: BigInt(validBefore),
    nonce: nonce,
  },
});

// --- Step 3: Build PaymentPayload, Base64-encode, and retry ---
const paymentPayload = {
  x402Version: 2,
  resource: paymentRequired.resource,
  accepted: accept,
  payload: {
    signature: signature,
    authorization: {
      from: account.address,
      to: accept.payTo,
      value: accept.amount,
      validAfter: "0",
      validBefore: validBefore.toString(),
      nonce: nonce,
    },
  },
};

const paymentHeader = btoa(JSON.stringify(paymentPayload));

const paidRes = await fetch(toolUrl, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "PAYMENT-SIGNATURE": paymentHeader,
  },
  body: requestBody,
});

const result = await paidRes.json();
console.log(result);
// { gateway: { cost, balance, request_id, x402_tx_hash }, data: { ... } }
```

### Method 2: @x402/fetch Wrapper (automatic)

Use the official x402 client library. It intercepts 402 responses, signs payment, and retries automatically.

**Dependencies:** `npm install @x402/fetch @x402/evm viem`

```javascript
import { x402Client, wrapFetchWithPayment } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { privateKeyToAccount } from "viem/accounts";

const client = new x402Client();
registerExactEvmScheme(client, {
  signer: privateKeyToAccount("0x..."),
});

const fetchWithPayment = wrapFetchWithPayment(fetch, client);

const toolUrl = "https://api.agenticgateway.io/v1/proxy/<toolId>";

const res = await fetchWithPayment(toolUrl, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ city: "London" }),
});

const result = await res.json();
console.log(result);
// { gateway: { cost, balance, request_id, x402_tx_hash }, data: { ... } }
```

To also support Solana payments, add the SVM scheme:

```javascript
import { registerExactSvmScheme } from "@x402/svm/exact/client";
import { createKeyPairSignerFromBytes } from "@solana/kit";
import { base58 } from "@scure/base";

registerExactSvmScheme(client, {
  signer: await createKeyPairSignerFromBytes(base58.decode(SVM_PRIVATE_KEY)),
});
```

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/deposit-address` | No | Returns `{ vault_address, solana_vault_address }` -- send USDC/USDT on Base L2 or Solana |
| GET | `/v1/tools` | No | All active/degraded tools with name, price, description |
| GET | `/v1/tools/search?query=...&mode=keyword` | No | Search tools (modes: `keyword`, `semantic`, `agentic`) |
| GET | `/v1/tools/:toolId` | No | Single tool details |
| GET | `/v1/account` | Yes | Your balance and recent deposits |
| POST | `/v1/proxy/:toolId` | Yes | Call an API tool -- body is forwarded to the supplier |
| GET | `/v1/transactions` | Yes | Paginated history (`?page=1&limit=20`) |
| GET | `/v1/transactions/:requestId` | Yes | Single transaction lookup |

## Response Format

### Success

```json
{
  "gateway": { "cost": 0.05, "balance": 49.95, "request_id": "uuid", "pricing": { "model": "per_request" } },
  "data": { "...supplier response..." }
}
```

### Failure (automatic refund)

```json
{
  "error": "API_FAILED",
  "message": "Supplier returned HTTP 500",
  "refund": { "amount": 0.05, "reason": "HTTP_500_ERROR", "new_balance": 50.00 }
}
```

### Timeout (202)

```json
{ "status": "pending", "message": "Supplier timed out", "request_id": "uuid" }
```

## Error Codes

| Code | HTTP | Meaning |
|---|---|---|
| `INSUFFICIENT_BALANCE` | 400/402 | Deposit more USDC, or use x402 pay-per-request (402 includes x402 payment info if enabled) |
| `TOOL_NOT_FOUND` | 404 | Invalid tool ID or tool is not active |
| `EXPIRED_TIMESTAMP` | 401 | Timestamp older than 5 minutes -- resend with fresh timestamp |
| `INVALID_SIGNATURE` | 401 | Signature does not match the request body + timestamp |
| `MISSING_AUTH` | 401 | Missing X-Signature or X-Timestamp headers (and x402 not enabled) |
| `INVALID_PAYMENT` | 402 | PAYMENT-SIGNATURE header could not be decoded |
| `PAYMENT_FAILED` | 402 | x402 payment verification or settlement failed |
| `MISSING_QUERY` | 400 | Search endpoint requires a `query` parameter |
| `INVALID_MODE` | 400 | Search mode must be `keyword`, `semantic`, or `agentic` |

## Search Modes

| Mode | How It Works | Latency |
|---|---|---|
| `keyword` (default) | Full-text + partial match + tag overlap in PostgreSQL | ~10ms |
| `semantic` | Embedding similarity via Cohere + pgvector | ~200-500ms |
| `agentic` | LLM reasons over the tool catalog to find the best match | ~1-3s |

```
GET /v1/tools/search?query=weather+forecast
GET /v1/tools/search?query=translate+text+to+spanish&mode=semantic
GET /v1/tools/search?query=I+need+to+resize+images+in+bulk&mode=agentic
```

## Pricing Models

**Per-request**: Flat USDC price per API call. Shown as `price` on the tool.

**Formula**: Cost calculated from a custom expression based on request parameters. Include the parameter values in your POST body. The gateway pre-authorizes the input formula cost. If the tool has an output pricing formula, the final cost is adjusted based on response data (capped at the pre-authorized amount), and any difference is refunded.

Formula tools include `pricing_model: "formula"`, `pricing_formula`, and `pricing_parameters` in the tool listing.
