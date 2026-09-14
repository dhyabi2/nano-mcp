#!/usr/bin/env python3
"""Consolidated evidence for `ledger verify --block 11` (all laws L0..L15).

Modeled on evidence_block10_full.py. For each active law quotes the strictest
assertion from its dedicated test plus a fresh pytest -v tail. Block 11's own
law L15 (P1's x402 reference-implementation draft) is proven by
tests/test_x402_draft_refimpl.py asserting the package structure, the fail-closed
two-RPC semantics, the atomic claim, and the subprocess typecheck/test runs.

Usage: python3 tools/evidence_block11.py OUT_FILE
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

LAW_PROOF = {
    "L0": ("test_crypto.py", [("test_private_key_derivation_matches_official_vector", "assert priv"),
                              ("test_public_key_derivation_matches_docs_keyexpand", "DOCS_PUB_EXPAND")]),
    "L1": ("test_client.py", [("test_live_balance_read", "account_balance"),
                              ("test_live_history_read", "account_history")]),
    "L3": ("test_wallet.py", [("test_send_over_balance_raises_without_publishing", "assert"),
                              ("test_send_over_daily_cap_raises_without_publishing", "assert")]),
    "L4": ("test_payments.py", [("test_l4_distinct_addresses_for_different_request_ids", "assert"),
                                ("test_l4_same_request_id_reproduces_same_address", "assert")]),
    "L5": ("test_payments.py", [("test_l5_approves_once_when_onchain_send_seen", "assert"),
                                ("test_l5_concurrent_claims_approve_exactly_once", "assert")]),
    "L6": ("test_probe.py", [("test_end_to_end_pay_per_call_succeeds_and_is_replay_safe", "assert")]),
    "L7": ("test_evidence.py", [("test_append_logs_external_once", "assert"),
                                ("test_append_never_logs_own_account", "assert")]),
    "L8": ("test_pricing.py", [("test_median_returns_middle_value", "assert"),
                               ("test_quote_usd_returns_exact_median_amount_and_no_money_moves", "assert")]),
    "L9": ("test_pricing.py", [("test_quote_expires_in_30_seconds_or_less", "expires_at"),
                               ("test_verify_refuses_expired_quote__does_not_approve", "expired")]),
    "L10": ("test_buyer.py", [("test_l10_valid_mandate_authorizes_send", "assert"),
                              ("test_l10_tampered_signature_refused_before_broadcast", "assert")]),
    "L11": ("test_buyer.py", [("test_l11_over_session_cap_refused", "assert"),
                              ("test_l11_over_daily_cap_refused", "assert"),
                              ("test_l11_over_balance_refused", "assert")]),
    "L12": ("test_scorecard.py", [("test_l12_share_counts_only_external_receipts", "share"),
                                  ("test_l12_own_traffic_adds_exactly_zero_to_share", "assert"),
                                  ("test_l13_verify_passes_on_published_raw_data", "assert"),
                                  ("test_l13_verify_detects_figure_drift", "assert")]),
    "L13": ("test_scorecard.py", [("test_l13_verify_passes_on_published_raw_data", "assert"),
                                  ("test_l13_verify_detects_figure_drift", "assert"),
                                  ("test_l12_share_counts_only_external_receipts", "share"),
                                  ("test_l12_own_traffic_adds_exactly_zero_to_share", "assert")]),
    "L14": ("test_x402_draft.py", [("test_spec_file_exists_at_x402_path", "SPEC.is_file"),
                                   ("test_spec_has_all_required_sections", "REQUIRED_SECTIONS"),
                                   ("test_spec_encodes_strategy_law_l1_two_independent_rpcs", "RPC endpoints"),
                                   ("test_no_upstream_pr_opened_by_default", "PENDING.read_text")]),
    "L15": ("test_x402_draft_refimpl.py", [
        ("test_refimpl_implements_the_three_core_interfaces", "SchemeNetworkClient"),
        ("test_refimpl_fail_closed_two_independent_rpcs", "verifyBlockOnIndependentEndpoints"),
        ("test_refimpl_atomic_single_use_claim", "claimStore.claim"),
        ("test_refimpl_typechecks_against_published_x402_core", "tsc --noEmit"),
        ("test_refimpl_own_ts_tests_pass", "npm test"),
        ("test_pending_frames_refimpl_and_opens_no_pr", "Approve so I (a) open PR 1"),
    ]),
}


def prove(fname: str, fns: list[tuple[str, str]]) -> str:
    txt = (TESTS / fname).read_text().splitlines()
    out = []
    for fn, needle in fns:
        idx = next((i for i, l in enumerate(txt) if re.match(rf"\s*def {re.escape(fn)}\(", l)), None)
        if idx is None:
            out.append(f"  ! def {fn} not found in {fname}")
            continue
        out.append(f"  -- {fname}::{fn} --")
        for i in range(idx, min(idx + 16, len(txt))):
            if needle in txt[i] and "assert" in txt[i] or i == idx:
                out.append(f"  {fname}:{i+1}: {txt[i].strip()}")
    return "\n".join(out)


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    parts = ["# Block 11 consolidated evidence (L0..L15)", "## Per-law quoted proof (test source)"]
    for law in sorted(LAW_PROOF, key=lambda l: int(l[1:])):
        f, fns = LAW_PROOF[law]
        parts.append(f"\n########## {law} ({f}) ##########\n" + prove(f, fns))
    parts.append("\n\n## Fresh full pytest -v (PASSED lines + summary)")
    run = subprocess.run([sys.executable, "-m", "pytest", "-v"],
                         cwd=ROOT, capture_output=True, text=True)
    lines = run.stdout.splitlines()
    passed = [ln for ln in lines if "PASSED" in ln or "passed" in ln.lower()]
    parts.append("\n".join(passed))
    if run.returncode:
        parts.append("STDERR:\n" + run.stderr[-1500:])
    body = "\n\n".join(parts)
    out.write_text(body)
    print(f"wrote {out} ({out.stat().st_size} bytes), pytest rc={run.returncode}")
    return 0 if run.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())