# Paying an XNO price when you only hold USDC

Most agents that buy over x402 hold USDC and no XNO. A seller can put an XNO price in its 402 and such a buyer
still cannot pay it. The way through is three steps, and only the middle one is a swap:

    USDC  --(swap service)-->  XNO in YOUR OWN account  --(send)-->  the seller

## Ask first, spend nothing

`plan_pay_from_usdc` (an MCP tool of this server, and a script) is read-only. It asks Nanswap's public quote
endpoints - no key, no account - whether an amount of USDC would cover a price, with 1% headroom.

    python3 nano_mcp/usdc_plan.py PAY_TO AMOUNT_RAW OWN_ACCOUNT USDC_AMOUNT NETWORK

`PAY_TO` and `AMOUNT_RAW` come from the seller's 402 entry. `OWN_ACCOUNT` is your nano_ account, where the swap
lands. `NETWORK` is the chain your USDC is on, such as `BASE`; it is required, with no default, in the script and
in the MCP tool alike. Exit 0 when the amount covers the price.

Run on 2026-11-12 for a 0.15 XNO price from 0.5 USDC on Base it answered `"covers": true`, an estimate of
1.32 XNO, and the service's limits that minute (0.173061 to 3279.971835 USDC). Under the minimum it says so and
asks for no estimate.

What it will not plan: a swap paid straight to the seller (the service would send what the swap yielded, not the
exact raw, from its own account, so the seller cannot match it to the call), a pair with no network named, a reply with
a non-2xx status, an estimate whose `amountFrom` is not the amount asked (or that leaves it out) or whose
`from` / `to`, when given, are not the pair asked, and any other reply from the service it does not understand.

## Then the hop itself

Creating the order needs a Nanswap API key, and the swap is custodial while it runs. This server does not do
that step. [`agent-wallet-multirail`](https://github.com/dhyabi2/agent-wallet-multirail)
(`pay_nano_quote_from_usdc`) does: it records the order so a retry cannot buy it twice, refuses an order that
does not name the planned chain, checks what arrived, and sends the seller the exact raw. As of 2026-11-12 its
quote half has been run against the live API and its order half has not (no key was available).

Swap cost that day, from the same public quotes: small amounts lose the most. Top up a few dollars once and pay
many calls from the XNO; do not swap per call.

## For a seller: the entry a USDC-holding buyer can plan against

Text to read, not a script to run. An XNO price sits beside the USDC one in `accepts[]`; nothing is replaced:

```json
{
  "scheme": "exact",
  "network": "nano:mainnet",
  "asset": "XNO",
  "amount": "150000000000000000000000000000",
  "payTo": "nano_YOUR_OWN_ACCOUNT"
}
```

- `amount` is raw, as a string of digits: 1 XNO = 10^30 raw, so the line above is 0.15 XNO.
- `payTo` is an account whose key you hold. Never one a helper or a thread gave you.
- To accept a payment: read the buyer's block from a public node and require that it is confirmed, is a send,
  pays your `payTo`, carries at least `amount`, and that the same block hash has not bought a call before.
