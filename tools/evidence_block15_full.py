"""Emit a consolidated L0..L22 evidence bundle for the block-15 ledger verify.

The ledger judge runs the FULL active law set (block<=15), and gather() truncates
evidence at ~60KB, so a single `--files` list cannot fit every test file — files
listed late (block 12-15: facilitator, httpx402, paidtool) get clipped and the
judge reports them 'missing evidence'. This generator quotes the ACTUAL asserting
test source per law into ONE evidence file so the judge sees real proof for every
law regardless of --files truncation (same discipline as tools/evidence_block13_full.py).
"""
import os
import re
import subprocess
import sys

REPO = "/root/nano-agent/nano-mcp"
PY = os.path.join(REPO, ".venv", "bin", "python")

# law -> (test_file, list of test-function names to quote)
# Order matters: the block-15 laws (L21/L22) and block 12-14 laws (L16-L20) are
# quoted FIRST so they survive the ~60KB gather() truncation no matter what else
# is on the command line. Earlier (block 2-8) laws follow and are lower priority.
LAW_TESTS: dict[str, tuple[str, list[str]]] = {
    "L21": ("tests/test_paidtool.py", ["test_replay_is_refused_once"]),
    "L22": ("tests/test_paidtool.py", ["test_execute_serves_result_after_verify_and_settle",
                                       "test_request_issues_one_time_payto",
                                       "test_fail_closed_single_endpoint_refuses",
                                       "test_wrong_amount_is_refused",
                                       "test_missing_request_id_is_refused"]),
    "L16": ("tests/test_facilitator.py", ["test_l16_facilitator_exposes_supported_verify_settle",
                                          "test_l16_fail_closed_when_any_endpoint_errors"]),
    "L17": ("tests/test_facilitator.py", ["test_l17_settle_re_verifies_then_claims_atomically"]),
    "L18": ("tests/test_facilitator_live.py", ["test_live_confirms_real_send_on_two_independent_public_rpcs"]),
    "L19": ("tests/test_httpx402.py", ["test_402_then_serves_after_settled_payment"]),
    "L20": ("tests/test_httpx402.py", ["test_spent_proof_never_serves_twice"]),
    "L0": ("tests/test_crypto.py",
           ["test_private_key_derivation_matches_official_vector",
            "test_address_matches_docs_keyexpand"]),
    "L1": ("tests/test_client.py", ["test_live_balance_read"]),
    "L3": ("tests/test_wallet.py",
           ["test_send_over_balance_raises_without_publishing",
            "test_send_over_daily_cap_raises_without_publishing"]),
    "L4": ("tests/test_payments.py", ["test_l4_distinct_addresses_for_different_request_ids",
                                      "test_l4_same_request_id_reproduces_same_address"]),
    "L5": ("tests/test_payments.py", ["test_l5_approves_once_when_onchain_send_seen"]),
    "L6": ("tests/test_probe.py", ["test_end_to_end_pay_per_call_succeeds_and_is_replay_safe"]),
    "L7": ("tests/test_evidence.py", ["test_append_logs_external_once"]),
    "L8": ("tests/test_pricing.py", ["test_quote_usd_returns_exact_median_amount_and_no_money_moves"]),
    "L9": ("tests/test_pricing.py", ["test_quote_expires_in_30_seconds_or_less",
                                     "test_verify_refuses_expired_quote__does_not_approve"]),
    "L10": ("tests/test_buyer.py", ["test_l10_valid_mandate_authorizes_send"]),
    "L11": ("tests/test_buyer.py", ["test_l11_over_session_cap_refused"]),
    "L12": ("tests/test_scorecard.py", ["test_l12_share_counts_only_external_receipts"]),
    "L13": ("tests/test_scorecard.py", ["test_l13_verify_passes_on_published_raw_data"]),
    "L14": ("tests/test_x402_draft.py", ["test_spec_file_exists_at_x402_path",
                                         "test_spec_payload_uses_nano_proof_and_network"]),
    "L15": ("tests/test_x402_draft_refimpl.py", ["test_refimpl_implements_the_three_core_interfaces"]),
}


def quote_source(path: str, func_names: list[str]) -> str:
    """Return the full source of each named test function with file:line prefixes.

    Captures the WHOLE body (up to 42 lines) INCLUDING internal blank lines, and
    stops only at the next top-level `def` — never at a blank line inside the
    function (a blank line between statements is not the function's end).
    """
    full = os.path.join(REPO, path)
    if not os.path.exists(full):
        return f"## {path}: FILE NOT FOUND\n"
    src = open(full, encoding="utf-8").read().splitlines()
    pieces: list[str] = []
    for name in func_names:
        top = re.compile(rf"^(async )?def {re.escape(name)}\(")
        for i, line in enumerate(src):
            if top.match(line.strip()):
                block: list[str] = []
                for j in range(i, min(len(src), i + 44)):
                    # stop at the next module-level function (col-0 'def ')
                    if j > i and re.match(r"^(async )?def ", src[j]):
                        break
                    block.append(src[j])
                quoted = "\n".join(f"{path}:{i+k+1}: {ln}" for k, ln in enumerate(block))
                pieces.append(quoted)
                break
    return "\n".join(pieces) or f"## {path}: could not locate {func_names}\n"


def main() -> str:
    lines: list[str] = []
    lines.append("=== BLOCK 15 CONSOLIDATED EVIDENCE L0..L22 (per-law source) ===")
    for law in [f"L{i}" for i in range(23)]:
        if law not in LAW_TESTS:
            continue
        path, funcs = LAW_TESTS[law]
        lines.append(f"## {law} — {path}: {funcs}")
        lines.append(quote_source(path, funcs))
    lines.append("=== pytest full-suite summary ===")
    try:
        out = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                             cwd=REPO, capture_output=True, text=True, timeout=360)
        lines.append(out.stdout[-800:])
        lines.append(f"pytest exit_code={out.returncode}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"pytest failed to run: {exc}")
    return "\n".join(lines)


if __name__ == "__main__":
    bundle = main()
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ev15_full2.txt"
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(bundle)
    print(f"{dest}: {len(bundle)} bytes")