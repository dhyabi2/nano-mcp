# nano-mcp plan (Law Ledger blocks)

Goal: an MCP server + small SDK so any AI agent can hold XNO and pay per API call in Nano,
transacting through the public node rpc.nano.to (live network, no local node, no issuer).

Invention (from ranking.md): self-custody SDK + MCP server. SDK signs sends locally and gets PoW
via rpc.nano.to `work_generate`; pay-per-call uses a server-derived ONE-TIME payment address per
request so the chain itself is the verifier (no memo, no trusted party, replay-safe, feeless).

Repo: /root/nano-agent/nano-mcp (git, private GitHub: PANDeveloper001). Tests: pytest (venv
`.venv` via uv). Checks: `uv run pytest` and mypy on changed files. Money rule: outbound
<= 0.01 XNO/day, never more than the wallet holds; seeds only in ~/.hermes/.env (chmod 600).

## Block 1 — PLAN (this session, done)
Scope: benchmark.md, benchmark-features.json, brainstorm 50 ideas (ideas.json), ranking.md,
this PLAN.md; laws below minted and verified against the plan docs.

## Block 2 — SDK core: derive & read (no sending yet)
- `nano_sdk/` package. `derive(seed) -> account(public_key, private_key, address, representative)`
  using ed25519-blake2b + blake2b-256 per Nano basics (seed+index → 32B priv; ed25519-blake2b pub;
  base32 Nano address with checksum).
- `client.py`: thin POST-JSON wrapper over NANO_RPC_URL, actions `account_balance` / `account_info`
  / `account_history`, returns nano-denominated values too.
- Unit tests with a KNOWN public test vector (docs.nano.org example seed → address) + live read
  of a known public account via rpc.nano.to.

Laws: L2.1 seed-based address derivation matches the official example.
L2.2 live reads (balance/history) work via rpc.nano.to without a local node.

## Block 3 — SDK send (sign + PoW + publish) — done this session
- `nano_sdk/block.py`: state-block byte construction (preamble 0x06 || account ||
  previous || representative || balance16 || link), blake2b-256 block hash, and
  Ed25519-Blake2b signing over that hash.
- `nano_sdk/wallet.py`: `Wallet` derives an account, reads account_info
  (balance/frontier/representative atomically), guards balance + daily cap
  (0.01 XNO/day), gets PoW via rpc.nano.to `work_generate`, builds+signs the send
  block, publishes via `process` (subtype=send, json_block=true).
- `client.process()` / `client.work_generate()` wrappers added.
- Tests: hash + signature verified against the docs *receive* vector
  byte-for-byte AND against live confirmed on-chain blocks (block_info ground
  truth); send-guard unit tests (over-balance and over-cap both raise before any
  broadcast). 28 passed (incl. live network tests).
- HONEST GAP: L2's full on-chain *confirmed send* (funds actually moving) is NOT
  run this session: no funded wallet exists in ~/.hermes/.env and AGENTS rules
  forbid seeking funds. The send *path* (sign/PoW/publish + guards) is built and
  its hash+signature mechanics are proven against the live chain; the final
  real-funds broadcast+confirmation is recorded as UNVERIFIED pending a funded
  test wallet.

Laws: L3.1 a signed send block is accepted and confirms on-chain via rpc.nano.to
(UNVERIFIED pending funded wallet — path built, hash/sig proven vs live chain).
L3.2 the SDK refuses to send more than the wallet holds / more than the daily
0.01 XNO cap (VERIFIED by unit tests).

## Block 4 — MCP server (pay-per-call tools) — done this session
- `nano_mcp/` package (new, mcp v2 where FastMCP -> MCPServer). Tools on an in-process
  stdio MCPServer: `get_address`, `get_balance`, `get_history`, `quote(price_nano,
  request_id?) -> {request_id, address, price_raw, price_nano}`, `pay_and_call(...)`
  (agent side: returns the one-time target + instructions), and service side
  `verify_payment(request_id, amount_raw)` which derives the same one-time address
  from the server master key, polls on-chain account_history, and returns approved
  once the matching send is confirmed — exactly once.
- One-time address derivation: HKDF-SHA256(server_master_secret, request_id) -> 32B
  Ed25519 private key -> nano_ address (`nano_mcp/oneshot.py`), deterministic per
  request_id, distinct across ids (L4).
- Exactly-once approval: SQLite-backed `INSERT ... PRIMARY KEY` claim in
  `nano_mcp/store.py` (brainstorm-converged), so one payment authorizes one call,
  replay-safe across restarts and concurrent calls (L5).
- Tests: `tests/test_payments.py` (L4 distinct+reproducible / L5 approve-once,
  persist, concurrency) + `tests/test_server.py` (drives the real MCPServer tools
  in-process via asyncio). 34 offline + 5 live pass (39 total).
- HONEST GAP: the *live-funded* on-chain confirmation of a real external payment
  (the chain fully moving XNO into a service address and being confirmed) reuses the
  same no-funded-wallet constraint as L2/L3 — it stays STUCK pending a funded test
  wallet. The verify machinery (account_history lookup + exactly-once claim) is
  proven against a stub client standing in for rpc.nano.to, consistent with the
  SDK's wallet-guard tests; the live-funded leg is recorded, not faked.

Laws: L4.1 the server derives a distinct, reproducible one-time address per
request_id (VERIFIED by unit + in-process MCP tests).
L4.2 `verify_payment(request_id)` approves a call only after the on-chain send to
that address is seen, and never twice for one request_id (VERIFIED by unit +
in-process MCP tests with a stub history client).

## Block 5 — end-to-end probe + evidence — done this session
- `nano_mcp/evidence.py` + `should_log()`: a payer is journaled as one `nano_tx`
  ONLY if it is NOT in `NANO_AGENT_OWN_ACCOUNTS` (own accounts never logged).
  The nano-pulse journal writer is injectable so it's testable against a scratch
  db without touching the real journal (`tests/test_evidence.py`, L7).
- `tests/test_probe.py`: one end-to-end scenario wires the real components with
  a chain stub — SDK wallet signs a send to the MCP one-time address (L0/L3),
  `quote` derives it (L4), `verify_payment` approves exactly once and a repeat
  returns spent (L5/L6), and the evidence gate journals the external payer but
  not the owner (L7). 45 tests pass (40 offline + 5 live).
- `ledger probe` → 88/100: L0,L1,L3,L4,L5,L6,L7 proven.
- HONEST GAP: L2 (a live funded on-chain send confirmed via rpc.nano.to) remains
  STUCK — no funded wallet, and AGENTS forbids seeking funds. The probe drives
  the same SDK→one-time-address→verify wiring on a chain stub so every real
  component is exercised; the final live-funded confirmation leg stays
  recorded-not-faked.

Laws: L6 end-to-end pay-per-call succeeds and is replay-safe (VERIFIED by probe).
L7 external payments are journaled as nano_tx, own accounts never (VERIFIED).

## Verification cadence
After each block: `ledger verify --block N` (second model, quoted evidence), then `ledger unwind`
for earlier laws, follow STUCK/Δ rules. Probe (block 5): one scenario, distinct evidence per law.