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

Block 2 (SDK derive + read) done and verified under the Law Ledger (`.ledger/`). Work proceeds in
blocks defined in `.ledger/PLAN.md`.