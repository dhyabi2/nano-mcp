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
- `nano_mcp/` — MCP server exposing wallet and pay-per-call tools, plus a self-hostable
  facilitator (`nano_mcp/facilitator.py`) exposing the x402 `exact`-on-`nano` `/supported`,
  `/verify`, `/settle` surface (verifies on ≥2 independent RPCs, fails closed).
- `tests/` — pytest; `nano_sdk/crypto.py` vectors are validated against the live node.

## Install / test

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
# NANO_RPC_URL + NANO_RPC_KEY must be set for live read/send tests
python -m pytest -m "not network"   # offline tests
python -m pytest                    # includes live rpc.nano.to reads
```

## Run it as an MCP server

Any MCP host starts the command the package installs and speaks JSON-RPC over its
stdin and stdout:

```bash
pip install .
nano-mcp                       # or: python -m nano_mcp.server
```

Or from the container, which is what an MCP directory builds. `-i` matters: stdio
is the transport, so the container has to keep its stdin.

```bash
docker build -t nano-mcp .
docker run -i --rm nano-mcp
```

Either way the server **starts with nothing configured** and lists all seven
tools, because that is the first thing a directory or a host asks it. The
read-only tools work unconfigured; the tools that derive a payment address
refuse until `NANO_PAYMENT_MASTER_SECRET` is set, naming it. No stand-in secret
is ever generated — a throwaway key would mint payment addresses whose private
keys die with the process, and XNO sent to one of those is unrecoverable.

To check that for yourself, exactly the way a directory does:

```bash
python tools/directory_handshake.py -- nano-mcp
# 7 tools: get_address, get_balance, get_history, pay_and_call, quote, quote_usd, verify_payment
# the handshake completed: a directory can start this server and list its tools
```

## Upgrade notes: payment proofs and the claim store

- Claims are case-insensitive on the block hash. One payment settles once
  whatever hex case its `paymentProof` is spelt in. The node is asked for the
  hash as sent, and `transaction` in verify/settle responses echoes it as sent.
- `consumption_key(block_hash, request_id)` now returns the hash upper-cased
  (the request_id is unchanged, and stays case-sensitive). `ClaimStore.claim`
  and `is_claimed` normalise the hash the same way.
- A custom `claim_store` receives both keys for a proof that is not spelt in
  upper case: `settle` asks its `is_claimed` (if it has one) about the key
  spelt exactly as sent, then calls `claim(<key as sent>)` and, only if that
  returns True, `claim(<canonical key>)`. A False from either is a duplicate,
  so a claim the store holds under an older spelling still counts even without
  `is_claimed`. The store must keep keys as given (not normalise them itself).
  An upper-case proof is claimed once, under the canonical key. If `is_claimed`
  raises (wrong signature, not callable, refuses the key), `settle` refuses
  with `errorReason: "claim_store_error"`; it does not raise or succeed.
- The built-in `ClaimStore` migrates an existing `claims.db` on every open: each
  old-spelling key also gets its canonical key (old rows are kept). It runs on
  every open, not once, so after a rollback and roll-forward the claims the
  previous release wrote in between are covered too; `PRAGMA user_version` is
  not used or changed. If the file is read-only or locked, the open still
  succeeds and the migration is retried on the next open. New claims are also
  stored under the key as sent, so a rollback to the previous release still
  finds them.
- The first open of a large old file does the real work once (about 1 s for
  100,000 lower-case claims) and roughly doubles the claims table, since each
  old row gains a canonical copy. Later opens re-check those old rows (about
  0.4 s per 100,000) and write nothing new unless a row lacks its copy.
- Not protected: a mixed fleet, i.e. the previous and this release writing one
  claim store at the same time. A payment the previous release claims in one
  spelling can settle once more through this release in another spelling until
  the store is next opened by this release. Upgrade every writer together.
- A `paymentProof` with a trailing newline (or any other character outside the
  64 hex digits) is refused.
- `PaidToolServer.execute` (`paid_tool_execute`) returns an `invalid` refusal
  for a malformed proof instead of raising `ValueError`.

## Address encoding (verified against the node)

`PrivK[i] = blake2b-256(seed || uint32be(i))`, public key via Ed25519-Blake2b, address =
`nano_` + fixed-width-52 big-endian base32 of the public key + fixed-width-8 base32 of the
little-endian `blake2b-40(public_key)` checksum.

## Status

Built and verified under the Law Ledger (`.ledger/`): blocks 2–15 done.

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
- Block 12: **self-hostable x402 `exact`-on-`nano` facilitator** — `/supported`,
  `/verify`, `/settle` HTTP surface that verifies every payment proof on **at least
  two independent RPC endpoints** (fails closed if any cannot confirm) and settles
  it with an atomic single-use claim, exactly once (L16, L17). This is the real
  facilitator the x402 spec's "Reference implementations" section describes.
- Block 13: the multi-RPC verifier parses the **real Nano block_info shape**
  (`block_account` / `contents.type` / `contents.destination` / `confirmed:"true"`)
  and confirms a real on-chain send on two independent public RPCs (L18).
- Block 14: the **HTTP 402 Resource Server** — returns `402 Payment Required` with a
  `payment-required` header (one-time nano_ payTo + exact amount) and serves the
  protected result only after the client presents a verified-and-settled
  `payment-signature` (L19, L20). The missing HTTP half of the x402 protocol.
- Block 15: the **MCP paidTool wrapper** (`nano_mcp/paidtool.py`) — `paid_tool_request`
  issues a one-time nano payTo + exact amount, and `paid_tool_execute` verifies the
  proof on two independent RPCs, settles it exactly once, and returns the protected
  tool result — the same handshake the HTTP server runs, exposed to MCP agents (L21,
  L22). Closes the last roadmap-stage-1 deliverable.

L2 (a live funded on-chain send confirmed via rpc.nano.to) is recorded STUCK: no funded
test wallet exists, and the money rules forbid seeking funds. Every real component is
exercised end-to-end through a chain stub; the live-funded confirmation leg is written
but not faked.