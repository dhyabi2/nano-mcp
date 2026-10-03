# Block 8 — open rail scorecard: ranked brainsstorm (25/25) → invention

Roadmap stage 4 (AGENTS.md): "Open rail scorecard — measured fee, finality and freeze
data per rail, published with raw data and a script that reproduces every figure.
Progress = Nano's share of observed agent payments; your own test traffic counts zero."
Binding strategy laws (rai-agent/strategy/.ledger): L5 (share only from public x402
counts + nano receipts whose payer is outside NANO_AGENT_OWN_ACCOUNTS; own traffic adds
zero), L6 (every figure reproducible from the published raw data).

## Ideas generated (block8-ideas.json, 25/25 with answers)

Rough clusters and verdict after full read:

| n  | idea | cluster | verdict |
|----|------|---------|---------|
| 16,17,15,19 | live measurement harness per rail; freeze-drill chaos | Per-rail empirical bench | CONTAINED: we cannot hold/forward others' money or open card/MPP/AP2 accounts under AGENTS; live sends capped at 0.01 XNO/day. Keep as the *method* (recorded, sourced) not the mechanism. |
| 3,18 | RailScope/RailScore: raw JSONL snapshot -> deterministic rebuild, hash, verify | Reproducible pipeline | CORE. Deterministic script over committed raw data, sha-verified rebuild, verify command. |
| 10,11,13,12 | hash-pinned manifest; reproducibility covenant; VeriRail run/verify/publish; docker kit | Tamper-evident reproducibility | CORE. Figure manifest (figure -> sha256(raw), script ver), `--verify` recompute-and-compare. Docker overkill for this repo; adopt the manifest+verify, not containers. |
| 21,23,22,24 | signed own-account registry; declared ID exclusion; one-time-address filter; honeypots | Own-traffic exclusion | ADOPT L5 via the existing evidence gate: `should_log` (nano_mcp/evidence.py) already excludes NANO_AGENT_OWN_ACCOUNTS. Reuse it; a signed registry is future polish, not MVP. |
| 0,1,2,20 | cross-rail PaymentID/nonce binding (memo/sidechain/IPFS intent log) | Cross-rail trace | REJECT for MVP: needs other rails to carry our nonce / memo (no permission), and Nano has no memo. Over-build; the share is already computable from public counts + our receipts. |
| 5,6,7,8 | canary network per rail / canary contracts | Network of canaries | DEFER: needs accounts/budgets on every rail (forbidden). We keep our own one-rail canary record as honest raw data, not fake cross-rail coverage. |
| 9 | peer-prediction truthfulness | Incentive scheme | REJECT: mechanism for *soliciting* third-party reports; none exist to solicit, and it risks requiring an external publish we cannot do unattended. |
| 14 | smart-contract dispute bond | Financial verification escrow | REJECT: needs a funded contract + chain interaction; over-engineering for this block's honest scope. |

## Winner (fusion)

`nano_mcp/scorecard.py`: a deterministic, network-free pipeline.

- **Raw data** (committed, versioned): `scorecard/raw/rails.json` (per-rail metric
  entries: rail, metric, value, unit, source, as_of — fee / finality_ms / freeze) and
  `scorecard/raw/x402.json` (public x402 agent-payment counts with source, as_of).
  Nano receipts come from a **journal reader** (same schema as nano-pulse) filtered by
  `should_log` so payers in NANO_AGENT_OWN_ACCOUNTS add zero (strategy L5).
- **Build**: `scorecard build --raw scorecard/raw --journal <db> --out scorecard/published.json`
  computes every published figure deterministically and writes a **manifest** mapping
  each figure -> sha256(raw record) used to derive it (strategy L6). No network; no
  import-time side effects.
- **Verify**: `scorecard verify --raw ... --manifest published.manifest.json` reruns the
  build and fails (non-zero) if any published figure differs from the manifest (L6 test:
  "running the script on the published raw data reproduces every published figure exactly").
- **Share**: nano_share = external_nano_receipts / (public_x402_count + external_nano_receipts),
  where external_nano_receipts counts only journal nano_tx rows whose payer !in own accounts.

## Laws at block/ledger scale

- L12 Share: "Nano's scorecard share comes only from public x402 counts plus nano
  receipts whose payer is outside NANO_AGENT_OWN_ACCOUNTS; Rai's own test payments add
  zero." -> satisfies strategy L5.
- L13 Reproducibility: "Every published scorecard figure is reproduced exactly by
  rerunning the scorecard build on the published raw data." -> satisfies strategy L6.

## Explicit non-goals (honesty)

No custody/transfer of others' money; no card/MPP/AP2 accounts opened; no fabricated
per-rail figures (every rail value must trace to a committed raw record with a source);
no network call inside build/verify; no external publish without human approval.