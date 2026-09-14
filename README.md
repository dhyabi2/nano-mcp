# nano-mcp

An **MCP server + SDK** so any AI agent can hold XNO (Nano) and pay per API call, transacting
through the public node **rpc.nano.to** (no local node, no issuer, no bridge).

Built by an **AI agent** (Rai). Tests are run against the live `rpc.nano.to` node.

## Why Nano

- **Feeless** — no per-transaction fee, so truly *per-call* (even micro) billing is economic; no batching.
- **Instant** — >99.9% of transactions settle in under a second.
- **Green** — no mining.
- **No issuer** — self-custody; nothing to freeze, no trusted third party to verify the payment.

## Repo layout

- `nano_sdk/` — pure-Python SDK: derive a wallet from a seed, read balance/history, and (later
  blocks) sign + publish sends via `rpc.nano.to`. Crypto is in `nano_sdk/crypto.py`.
- `nano_mcp/` — MCP server exposing wallet and pay-per-call tools (later blocks).
- `tests/` — pytest; `nano_sdk/crypto.py` vectors are validated against the live node.

## Install / test

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
# NANO_RPC_URL + NANO_RPC_KEY must be set for live read/send tests
python -m pytest -m "not network"   # offline tests
python -m pytest                    # includes live rpc.nano.to reads
```

## Address encoding (verified against the node)

`PrivK[i] = blake2b-256(seed || uint32be(i))`, public key via Ed25519-Blake2b, address =
`nano_` + fixed-width-52 big-endian base32 of the public key + fixed-width-8 base32 of the
little-endian `blake2b-40(public_key)` checksum.

## Status

Built and verified under the Law Ledger (`.ledger/`): blocks 2–7 done.

- Block 2: SDK derive + live read (L0, L1).
- Block 3: SDK send (sign + PoW + publish) with balance + 0.01 XNO/day cap guards (L3).
- Block 4: MCP pay-per-call server — one-time address per request (L4), exactly-once
  `verify_payment` (L5).
- Block 5: end-to-end probe (L6) + evidence gate that journals a payment as `nano_tx`
  only if it comes from an account we do NOT control (L7). `ledger probe` → 88/100.
- Block 6: dollar-priced quotes — the exact XNO for a USD price from the **median of
  three** independent sources, expiring in ≤30s, pure computation (L8, L9).
- Block 7: **Buyer SDK** — owner-signed Ed25519 `Mandate` + capped per-session
  sub-accounts. `SessionWallet` lets an owner delegate *limited, expiring* spending
  authority to an autonomous agent: it verifies the owner signature, the session
  binding, the per-session cap, the 0.01 XNO/day cap and the balance guard before
  any block is broadcast, so a compromised agent cannot drain the wallet (L10, L11).

L2 (a live funded on-chain send confirmed via rpc.nano.to) is recorded STUCK: no funded
test wallet exists, and the money rules forbid seeking funds. Every real component is
exercised end-to-end through a chain stub; the live-funded confirmation leg is written
but not faked.