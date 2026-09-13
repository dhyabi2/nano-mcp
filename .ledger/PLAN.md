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

## Block 3 — SDK send (sign + PoW + publish)
- Construct/sign a state block (send + receive), sign with ed25519_blake2b over blake2b-256 block
  hash (per block-format doc), obtain PoW via rpc.nano.to `work_generate` (frontier), publish via
  rpc.nano.to `process`.
- Guard: refuse amount > available balance; respect <= 0.01 XNO/day outbound cap.
- Live test only between accounts the agent controls, smallest amounts.

Laws: L3.1 a signed send block is accepted and confirms on-chain via rpc.nano.to.
L3.2 the SDK refuses to send more than the wallet holds / more than the daily 0.01 XNO cap.

## Block 4 — MCP server (pay-per-call tools)
- `nano_mcp/` FastMCP stdio server. Tools: `get_address`, `get_balance`, `get_history`,
  `quote(tool, args) -> {price_raw, addr, request_id}`, `pay_and_call(...)` (agent side: send then
  call), and service side `verify_payment(request_id)` (derives the same one-time address from the
  server master key, polls account_history, returns approved once the matching send arrives).
- One-time address derivation: HKDF-SHA256(server_master_secret, request_id) -> Nano keypair.
- Tests: in-process MCP client drives tools; keypair-for-request_id is deterministic and unique.

Laws: L4.1 the server derives a distinct, reproducible one-time address per request_id.
L4.2 `verify_payment(request_id)` approves a call only after the on-chain send to that address is
seen, and never twice for one request_id.

## Block 5 — end-to-end probe + evidence
- One agent (SDK) pays the service (MCP) and gets the gated tool result; run `ledger probe`.
- Wire evidence: when a payment arrives from an account NOT in NANO_AGENT_OWN_ACCOUNTS, append a
  `nano_tx` event to the nano-pulse journal (AGENTS.md snippet). Never log our own accounts.
- README (built-by-AI claim) and private pushes per run.

Laws: L5.1 an end-to-end pay-per-call succeeds and is replay-safe (single execution).
L5.2 external payments are journaled as nano_tx to nano-pulse; none of our own accounts are ever
logged.

## Verification cadence
After each block: `ledger verify --block N` (second model, quoted evidence), then `ledger unwind`
for earlier laws, follow STUCK/Δ rules. Probe (block 5): one scenario, distinct evidence per law.