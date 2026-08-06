# Handsel public environment-label audit

Audit date: 2026-08-07 JST  
Taskmarket target: `0x7eeff4e1991bd0d40eee406777fc568abf341ecff3368d991f89cf9d0d6f6e04`

## Executive finding

**The public surfaces reviewed do not state the literal labels `mainnet` or `testnet`.**

They do communicate that the system is non-live through other language: the homepage identifies Stripe test mode, says real money does not move until a human gate is cleared, and states that no external vendor is live; the playground identifies itself as a sandbox, Stripe-free, and settled at zero dollars. That is materially honest, but the environment state is spread across prose rather than expressed as one persistent, unambiguous label.

## Evidence matrix

| Public surface | `mainnet` literal | `testnet` literal | Environment signals actually present | Finding |
|---|---:|---:|---|---|
| `https://handsel.ai/` | 0 | 0 | Stripe test mode; no real-money movement until counsel approval; sandbox is free; no external vendor live yet | Clearly non-live when read closely, but not labeled with the requested terms |
| `https://handsel.ai/playground` | 0 | 0 | Sandbox tier; Stripe-free; zero-dollar settlement; hosted playground not live | Clear sandbox semantics, but no literal mainnet/testnet marker |

Searches were case-insensitive against the rendered public text available on the audit date. Private specifications, unpublished SDK repositories, authenticated dashboards, and future deployments were outside scope.

## Why the current presentation can still confuse

1. The safety-qualified statements are separated from prominent product language.
2. The homepage also uses forward-looking phrases such as connecting Stripe and going live. A reader can encounter those before the strongest non-live qualification.
3. `sandbox`, `Stripe test mode`, and `not live` describe related but different states. Readers must infer how they fit together.
4. `mainnet` and `testnet` are blockchain-network terms, while Handsel is also describing payment and product-readiness states. Using them without qualification could introduce a different ambiguity.

## Recommended label system

Use one persistent environment badge in the global header and repeat it beside every action that could be mistaken for a real-money operation.

### Current state

```text
ENVIRONMENT: TEST
Stripe test mode · no live payments · external vendors not live
```

### Playground

```text
PLAYGROUND: SANDBOX
Ephemeral · Stripe-free · settlement fixed at $0
```

### Future production state

Only after the stated legal and operational gate is complete:

```text
ENVIRONMENT: LIVE
Real payments enabled
```

Use `Base mainnet`, `Base testnet`, or another network label only when identifying an actual settlement network. Use `TEST` and `LIVE` for product/payment state. This avoids implying that Stripe test mode is itself a blockchain testnet.

## Suggested implementation locations

- Global navigation badge on every public page.
- Immediately above any `claim`, `connect Stripe`, or `go live` action.
- In the quickstart before the first command.
- In playground trace output and generated receipts.
- In machine-readable metadata such as `/llms.txt` and well-known documents.

Suggested machine-readable fields:

```json
{
  "product_environment": "test",
  "payment_mode": "stripe_test",
  "live_payments_enabled": false,
  "external_vendors_live": false,
  "settlement_network": null
}
```

## Acceptance checks

1. A first-time reader can identify the current payment state without scrolling.
2. `ENVIRONMENT: TEST` appears on the homepage, playground, and quickstart.
3. Every action containing `claim`, `connect`, or `go live` has adjacent state text.
4. Machine-readable metadata exposes the four state fields above.
5. A regression test fails if a live-payment call-to-action is rendered without the environment badge.
6. `mainnet` or `testnet` is never used without naming the network it qualifies.

## Conclusion

The accurate answer to the task title is **no: literal mainnet/testnet labels are not stated on the public surfaces reviewed**. The site does provide several honest non-live qualifications, so this is a clarity and placement defect rather than evidence of concealed live payments. A persistent TEST/LIVE payment-state badge, with network names handled separately, would resolve the ambiguity without overstating the product's current readiness.
