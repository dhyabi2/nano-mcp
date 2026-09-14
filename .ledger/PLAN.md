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

## Block 6 — dollar-priced quotes (USD price → exact XNO via median of 3) — done this session
- `nano_mcp/pricing.py`: USD→XNO conversion as PURE computation (no custody, no
  conversion, no chain contact). Fetches the USD/XNO rate from THREE independent
  public sources (CoinGecko, CoinPaprika, Kucoin), takes the MEDIAN, and converts
  a USD price to the exact integer raw XNO via rounding UP (ceiling) so the seller
  never under-receives. Tolerates one source failing; requires ≥2 healthy. All
  money math in Decimal (1 XNO = 10^30 raw), raw always an integer.
- `PaymentService.quote_usd(price_usd)` returns {request_id, address, price_raw,
  price_usd, rate_xno_usd, expires_at} with `expires_at = now + 30s`; the expiry is
  recorded in the store so `verify_payment` refuses a payment made after the 30s
  honour window (status='expired', never approved). `rate_source`/`clock` are
  injectable for offline tests.
- `quote_usd` MCP tool added. L8 (exact median XNO amount + no money moves) and
  L9 (≤30s expiry) minted. 12 new tests (offline median/ceil/expiry onto a fixed
  rate; a spy client proving the quote path performs NO chain contact; live
  median-of-three-source numeric test). 58 tests pass (46 offline + 12, incl.
  2 live network).
- ledger verify block 6: L0,L1,L3,L4,L5,L6,L7,L8,L9 PASS; L2 STUCK (no funded
  wallet — the standing honest gap from block 3, not a regression). Block 6's own
  laws L8/L9 PASS.

Laws: L8 a USD-price quote yields the exact XNO amount from the MEDIAN of three
independent sources and never holds/converts money (VERIFIED offline across all
laws + live median test).
L9 a dollar quote expires within 30 seconds (VERIFIED: quote TTL ≤30s and
verify_payment returns 'expired' and never approves past the window).

## Block 7 — Buyer SDK (owner-signed mandates + capped per-session sub-accounts) — done this session
- `nano_sdk/buyer.py` — Roadmap stage 3. Solves the "an autonomous/compromised
  agent holding spend authority could drain the wallet" risk:
  - `derive_session_account(master_seed, session_id)`: HKDF-SHA256 sub-account
    deterministic per session, distinct across sessions, so a leaked session
    key cannot derive or spend another session's share (test asserts two
    session_ids differ and repeats reproduce).
  - `Mandate` + `issue_mandate`/`verify_mandate`: the OWNER signs
    {session_id, address(es bound sub-account), cap_raw, issued_at, expires_at,
    nonce} with their Ed25519 private key. Nothing in the grant can be edited
    without breaking the signature; it cannot be replayed past expiry.
  - `SessionWallet.check_spend`/`send`: fail-closed, ALL checks BEFORE any block
    is built or broadcast — owner signature, unexpired, address binding
    (mandate.address == this session's account) (L10); per-session cap, the
    0.01 XNO/day cap, and the on-chain balance guard (L11).
- `tests/test_buyer.py`: 10 new tests (valid mandate authorizes; tampered /
  wrong-key / expired / misbound all refuse with no process call; over-session /
  over-daily / over-balance refuse with no process call; up-to-cap allowed and
  recorded; session-sub isolation). 68 tests pass.
- ledger verify block 7: L0,L1,L3,L4,L5,L6,L7,L8,L9,L10,L11 PASS; L2 STUCK
  (no funded wallet — the standing honest gap from block 3, not a regression).
  Block 7's own laws L10/L11 PASS.

Laws: L10 a buyer session spends only under a valid owner-signed, unexpired
mandate bound to its own sub-account (VERIFIED).
L11 the SDK enforces a per-session cap, the daily cap, and the balance guard
before broadcast (VERIFIED).

## Block 8 — open rail scorecard (roadmap stage 4) — done this session
- `nano_mcp/scorecard.py` — deterministic, network-free pipeline. `build` reads
  ONLY committed raw files (`scorecard/raw/rails.json` per-rail fee/finality/freeze
  records with source+method+as_of, `scorecard/raw/x402.json` the public x402
  count) plus an injected journal reader, and computes every published figure
  plus `share_of_observed = external_receipts / (x402_count + external_receipts)`
  where external receipts are journal rows whose payer is NOT in
  NANO_AGENT_OWN_ACCOUNTS (the same evidence gate as `nano_mcp/evidence.py`
  `should_log`). No network, no chain contact, byte-identical on re-run.
- `scorecard build --raw ... --out published.json --manifest manifest.json` writes
  a manifest mapping every published figure to the SHA-256 of the raw record(s)
  that produced it; `scorecard verify` reruns the build and FAILS if any figure
  differs (strategy law L6). CLI covered by `tests/test_scorecard.py`
  (L12 share-only-external / L13 reproducibility), 10 new tests.
- ledger verify block 8 (full evidence bundle `tools/evidence_block8.py` ->
  per-law quoted test source + fresh `pytest -v`): L0,L1,L3,L4,L5,L6,L7,L8,L9,
  L10,L11,L12,L13 PASS; L2 STUCK (no funded wallet — the standing honest gap from
  block 3, not a regression). Block 8's own laws L12/L13 PASS.
- 78 tests pass in total (68 from block 7 + 10 new scorecard).
- HONEST GAP: L2 (a live funded on-chain send confirmed via rpc.nano.to) remains
  STUCK — no funded wallet, AGENTS forbids seeking funds. The scorecard's share
  therefore reads 0 today (no external receipts), which is the truth: Rai's own
  traffic adds zero (L12).

Laws: L12 Nano's scorecard share comes only from public x402 counts plus nano
receipts whose payer is outside NANO_AGENT_OWN_ACCOUNTS; Rai's own test payments
add exactly zero to the share (VERIFIED).
L13 Every published scorecard figure is reproduced exactly by rerunning the
scorecard build on the published raw data (VERIFIED: build==verify passes on
committed raw; tampering a raw figure makes verify fail).

## Block 9 — distribution without permission (roadmap stage 5) — INITIATED this run
- Roadmap stage 1–4 implemented across blocks 2–8 (nano scheme/facilitator + MCP
  paidTool, dollar-priced quotes, buyer SDK, open rail scorecard). 78 tests pass.
- Stage 5 is outward-facing (upstream PRs), so per AGENTS.md "Public actions" it
  must be proposed in pending.md first; Rai must NOT open the PRs itself.
- This run: benchmarked the concrete target (x402 Foundation `x402` open-source
  SDK), confirmed its CONTRIBUTING.md accepts new schemes/chains via a spec-first
  two-PR workflow (`scheme_<scheme>_<chain>.md` spec, then one-SDK reference
  implementation of `SchemeNetworkClient/Server/Facilitator`; no core changes).
- Wrote proposal **P1** to ~/nano-agent/pending.md: add a `nano` (XNO) scheme to x402,
  describing exactly what blocks 2–8 already build/verify (one-time address, ≥2 RPC
  verification, self-hostable facilitator). NO PR submitted (awaiting human approval).
- HONEST GAP: L2 (live funded on-chain send) remains STUCK as before (no funded
  wallet, forbids seeking funds). Nothing in this block fakes it.

Laws: none minted this run (block adds no new code; pending.md proposal is outward-
facing and requires human approval before any PR can exist to verify against).
