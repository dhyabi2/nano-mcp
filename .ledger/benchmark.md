# Benchmark: best existing solution for "AI agent holds XNO and pays per API call"

Goal restated: an MCP server + small SDK so any AI agent can hold XNO and pay per API call in
Nano, transacting through the public node rpc.nano.to.

Sources checked live today:
- rpc.nano.to responds (POST JSON): `version` -> node_vendor "Nano V28.2", network live (verified).
- docs.nano.to/nano-rpc : full node RPC actions (account_balance, account_info, block, work_generate...).
- docs.nano.to/pow : GPU Proof-of-Work API (work_generate + api key; free 30 PoW / 30 min).
- docs.nano.org/integration-guides/the-basics : Nano block-lattice, blake2b-256 block hash,
  ed25519-blake2b (512) signature, 64-bit work (PoW) field.
- GitHub nkr0/nanopy : pure-ish Python Nano lib (C ext for work+sign), RPC to a node.
- PyPI ed25519-blake2b-fork : pure-Python Ed25519-Blake2b signing (verified importable).
- rpc.nano.to/ : official CLI `@nano/wallet` (npm), 5 commands send/receive.
- npm @openrai/nano-core : JS SDK, wallet hydrate + RPC pool failover to rpc.nano.to.
- Pay-per-call for agents today: x402 (spec + MCP servers, USDC/stablecoin), Eco, Nevermined,
  Crossmint, AP2, Bitnovo Pay MCP, Zuplo MCP-payments — all stablecoin/trusted-verifier based.

## Table: what makes each leader best, and its reason

| # | Feature | Why it is the best existing thing | Source |
|---|---------|----------------------------------|--------|
| F1 | x402 stablecoin per-call settlement | Proven design: agent pre-authorizes, trusted "x402 server" verifies USDC transfer, releases HTTP 402; integrates with MCP servers today | zuplo.com/blog/mcp-api-payments-with-x402, eco.com/support/14846274 |
| F2 | On-chain payment verification | Money moves on-chain; a trusted verifier attests transfer before serving | x402 spec / Zuplo |
| F3 | Self-custody wallet SDK | `@openrai/nano-core` hydrates Nano wallet from seed, RPC-pool failover across rpc.nano.to etc. | npm @openrai/nano-core |
| F4 | Service price/gate tooling | Bitnovo Pay MCP, Stripe Machine Payments: service sets price, agent pays, server serves | mcpservers.org + nevermined blog |
| F5 | Program-reproducible flow | CLI `@nano/wallet`: generate / faucet / receive / balance / send in 5 commands | rpc.nano.to/ |
| F6 | Node-less instant usability | rpc.nano.to is a full live node over HTTP; Nano CLI + RPC docs make transacting possible without running a node | docs.nano.to/nano-rpc |
| F7 | (see brainstorm F7–F10 design axes) | open design questions for the pay-per-call mechanism | — |

## Why Nano beats the stablecoin incumbent for THIS goal

- x402/USDC needs a trusted verifier interposed per call and must batch tiny charges because
  stablecoin settlement carries fees + an issuer that can freeze funds.
- Nano is feeless (per-call micro-payments economic, no batching), instant (>99.9% <1 s), green
  (no mining), and has NO issuer (self-custody, nothing to freeze, no bridge).
- rpc.nano.to gives us a live node over HTTPS for free — the SDK + MCP server need no local node.

## Weakness of the current best that we must beat

The JS @openrai/nano-core + x402 stack is library-/verifier-specific and jargon-heavy; there is no
agreed tool that makes a Nano agent wallet + per-call payment feel native inside an MCP server.
That integration (SDK wallet + MCP pay-per-call tools) is the gap nano-mcp fills.