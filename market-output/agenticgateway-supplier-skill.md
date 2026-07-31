# Agentic Gateway -- Supplier Integration Skill

## What This Is

A guide for suppliers who want to list their API on the Agentic Gateway marketplace. Once listed, AI agents worldwide can discover and pay for your API with USDC/USDT. You earn crypto for every successful call.

## Base URL

`https://agenticgateway.io` (frontend) / `https://api.agenticgateway.io` (API)

## Quick Start

```
1. Connect wallet at https://agenticgateway.io → go to Supplier Dashboard
2. Click "Submit New Tool" → fill in endpoint URL, pricing, parameters, and description
3. Pay the listing deposit → tool goes to "Pending" for admin review
4. Once approved → your API is live on the marketplace and discoverable by agents
```

## Tool Submission (via UI)

Go to `/supplier/tools/new` on the frontend. You will need:

- **Tool Name** and **Description** (Markdown supported — agents rely on this to decide which tool to call)
- **Endpoint URL** — the POST endpoint the gateway will proxy requests to
- **Pricing Model** — `per_request` (flat price per call) or `formula` (dynamic pricing based on request parameters)
- **Input Parameters** — define typed parameters with constraints (integer, number, string, boolean, list). These generate the example request and validate incoming calls.
- **Test Endpoint** — click to verify your endpoint is reachable and returns valid JSON. The response is auto-captured as the example response.
- **Output-Based Pricing** (optional) — define a second formula evaluated against response data. Final cost is the lesser of input and output formula, with the difference refunded.

## Gateway Secret

When your tool is approved, you receive a 64-character hex `gateway_secret`. The gateway sends this as the `X-Gateway-Secret` header on every proxied request. **Verify this header** in your API to ensure requests come from the gateway.

```javascript
app.use((req, res, next) => {
  if (req.headers['x-gateway-secret'] !== process.env.GATEWAY_SECRET)
    return res.status(401).json({ error: 'Unauthorized' });
  next();
});
```

## How Requests Reach You

```
Agent → POST /v1/proxy/:toolId → Gateway validates, deducts balance → POST your_endpoint_url
                                                                       with X-Gateway-Secret header
                                                                       and the agent's request body
```

Your API receives the raw request body from the agent. Return standard JSON. The gateway wraps your response for the caller.

## Pricing Models

**Per Request** — flat USDC price per call. Set the price when submitting your tool.

**Formula** — dynamic pricing based on request parameters. Define:
- A base price (available as `base_price` in the formula)
- Typed parameters with constraints (min/max, type validation)
- A formula expression: e.g. `base_price * num_images * (high_def ? 2 : 1)`

**Output-Based Pricing** (optional, works with both models) — define output parameters extracted from your API response and a second formula. The gateway evaluates it post-response and charges the lesser amount. Example: pre-authorize for 10 images, but only charge for 3 if that's what was generated.

## Earnings & Withdrawals

- Earnings settle after 7 days
- View available vs. pending balance on the Supplier Dashboard
- Withdraw to USDC or USDT on Base L2

## Supplier API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | /v1/supplier/register | Register a new tool (requires deposit) |
| GET | /v1/supplier/status | Dashboard: tools, balances, earnings |
| PATCH | /v1/supplier/tools/:toolId | Update tool details |
| POST | /v1/supplier/tools/draft | Save/update a draft (no deposit) |
| POST | /v1/supplier/tools/:toolId/submit | Submit a draft for review (requires deposit) |
| POST | /v1/supplier/tools/test-endpoint | Test an endpoint URL |
| POST | /v1/supplier/tools/:toolId/rotate-key | Rotate gateway secret |
| POST | /v1/supplier/withdraw | Request withdrawal of settled earnings |

## Response Format

Return standard JSON from your endpoint. The gateway wraps it:

```json
{
  "gateway": {
    "cost": 0.05,
    "balance": 49.95,
    "request_id": "d4e5f6..."
  },
  "data": { "your": "response" }
}
```

If your API returns HTTP 4xx/5xx or times out (15s), the agent is automatically refunded.
