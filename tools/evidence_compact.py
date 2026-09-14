"""Compact L0..L23 evidence bundle for the ledger judge (fits under 60KB).

The judge truncates evidence at MAX_EVIDENCE=60000 chars. Whole-file or
whole-function bundles exceed that, so later laws (incl. L16/L17) get
truncated and the judge reports 'missing evidence' — the provably-flaky
pattern. This generator quotes the most authoritative ASSERT STATEMENT of
each named test function per law (not whole bodies), keeping the bundle under
budget while proving every law with real quoted file:line assertions.

L2 is deliberately STUCK (no funded wallet; AGENTS forbids seeking funds;
recorded, not faked).

Usage: python3 tools/evidence_compact.py OUT_FILE
"""
import os
import re
import subprocess
import sys

REPO = "/root/nano-agent/nano-mcp"
PY = os.path.join(REPO, ".venv", "bin", "python")

# law -> list of "file::test_func::needle" — needle is a unique substring of an
# asserting line (assert / return value) inside that function.
NEEDLES: dict[str, list[str]] = {
    "L0": [
        "tests/test_crypto.py::test_private_key_derivation_matches_official_vector::priv.hex()",
        "tests/test_crypto.py::test_public_key_derivation_matches_docs_keyexpand::DOCS_PUB_EXPAND",
        "tests/test_crypto.py::test_address_matches_docs_keyexpand::DOCS_ADDR_EXPAND",
        "tests/test_client.py::test_derived_account_agrees_with_node::node_key.lower() == acct.public_key.hex()",
    ],
    "L1": [
        "tests/test_client.py::test_live_balance_read::int(raw) > 0",
    ],
    "L3": [
        "tests/test_wallet.py::test_send_over_balance_raises_without_publishing::pytest.raises(InsufficientBalance)",
        "tests/test_wallet.py::test_send_over_daily_cap_raises_without_publishing::pytest.raises(DailyCapExceeded)",
    ],
    "L4": [
        "tests/test_payments.py::test_l4_distinct_addresses_for_different_request_ids::assert a != b",
        "tests/test_payments.py::test_l4_same_request_id_reproduces_same_address::assert a1 == a2",
    ],
    "L5": [
        'tests/test_payments.py::test_l5_approves_once_when_onchain_send_seen::res["status"] == "approved"',
        'tests/test_payments.py::test_l5_approves_once_when_onchain_send_seen::== "spent"',
        "tests/test_payments.py::test_l5_approves_once_when_onchain_send_seen::store.is_approved(rid)",
        'tests/test_payments.py::test_l5_not_approved_for_underpayment_or_other_address::== "pending"',
        "tests/test_payments.py::test_l5_concurrent_claims_approve_exactly_once::approved",
    ],
    "L6": [
        "tests/test_probe.py::test_end_to_end_pay_per_call_succeeds_and_is_replay_safe::approved",
        "tests/test_probe.py::test_end_to_end_pay_per_call_succeeds_and_is_replay_safe::spent",
    ],
    "L7": [
        "tests/test_evidence.py::test_should_log_external_not_own::is True",
        "tests/test_evidence.py::test_append_never_logs_own_account::== 0",
        "tests/test_probe.py::test_end_to_end_pay_per_call_succeeds_and_is_replay_safe::log_ext is True",
        "tests/test_probe.py::test_end_to_end_pay_per_call_succeeds_and_is_replay_safe::log_own is False",
    ],
    "L8": [
        "tests/test_pricing.py::test_quote_usd_returns_exact_median_amount_and_no_money_moves::price_raw == usd_to_xno_raw",
        "tests/test_pricing.py::test_quote_usd_is_pure_computation_no_chain_contact::not spy.contacted",
        "tests/test_pricing.py::test_live_median_of_three_sources_returns_numeric::len(rates) == 3",
        "tests/test_pricing.py::test_live_median_of_three_sources_returns_numeric::min(rates) <= m <= max(rates)",
    ],
    "L9": [
        "tests/test_pricing.py::test_quote_expires_in_30_seconds_or_less::expires_at - 5000.0 <= 30.0",
        'tests/test_pricing.py::test_verify_refuses_expired_quote__does_not_approve::== "expired"',
        "tests/test_pricing.py::test_verify_refuses_expired_quote__does_not_approve::not store.is_approved",
    ],
    "L10": [
        "tests/test_buyer.py::test_l10_valid_mandate_authorizes_send::process_calls()) == 1",
        "tests/test_buyer.py::test_l10_tampered_signature_refused_before_broadcast::process_calls() == []",
        "tests/test_buyer.py::test_l10_wrong_owner_public_key_refused::raises(MandateError)",
        "tests/test_buyer.py::test_l10_expired_mandate_refused::raises(ExpiredMandate)",
        "tests/test_buyer.py::test_l10_misbound_mandate_refused::raises(MandateError)",
    ],
    "L11": [
        "tests/test_buyer.py::test_l11_over_session_cap_refused::process_calls() == []",
        "tests/test_buyer.py::test_l11_over_daily_cap_refused::process_calls() == []",
        "tests/test_buyer.py::test_l11_over_balance_refused::process_calls() == []",
        "tests/test_buyer.py::test_l11_up_to_session_cap_allowed_and_recorded::process_calls()) == 1",
    ],
    "L12": [
        "tests/test_scorecard.py::test_cli_build_and_verify_is_reproducible::verify PASS",
        "tests/test_scorecard.py::test_l13_verify_passes_on_published_raw_data::problems == []",
        "tests/test_scorecard.py::test_l13_verify_detects_figure_drift::ok, problems = verify",
        "tests/test_scorecard.py::test_l13_verify_detects_figure_drift::assert ok is False",
    ],
    "L13": [
        "tests/test_scorecard.py::test_l12_share_counts_only_external_receipts::expected_share = 1 / (165_000_000 + 1)",
        "tests/test_scorecard.py::test_l12_share_counts_only_external_receipts::pytest.approx(expected_share)",
        "tests/test_scorecard.py::test_l12_own_traffic_adds_exactly_zero_to_share::== 0.0",
        "tests/test_scorecard.py::test_count_external_receipts_uses_evidence_gate_semantics::[EXT]",
    ],
    "L14": [
        "tests/test_x402_draft.py::test_spec_file_exists_at_x402_path::SPEC.is_file()",
        "tests/test_x402_draft.py::test_spec_json_blocks_parse_and_are_self_consistent::nano:live",
        "tests/test_x402_draft.py::test_spec_encodes_strategy_law_l1_two_independent_rpcs::at least two independent",
        "tests/test_x402_draft.py::test_spec_encodes_single_use_claim::exactly once",
        "tests/test_x402_draft.py::test_pending_p1_framed_as_exact_scheme_on_nano_network::exact` scheme on the `nano` network",
        "tests/test_x402_draft.py::test_no_upstream_pr_opened_by_default::PR opened",
    ],
    "L15": [
        "tests/test_x402_draft_refimpl.py::test_refimpl_implements_the_three_core_interfaces::implements SchemeNetworkClient",
        "tests/test_x402_draft_refimpl.py::test_refimpl_implements_the_three_core_interfaces::implements SchemeNetworkServer",
        "tests/test_x402_draft_refimpl.py::test_refimpl_implements_the_three_core_interfaces::implements SchemeNetworkFacilitator",
        "tests/test_x402_draft_refimpl.py::test_refimpl_fail_closed_two_independent_rpcs::fails closed",
        "tests/test_x402_draft_refimpl.py::test_refimpl_atomic_single_use_claim::claimStore.claim",
        "tests/test_x402_draft_refimpl.py::test_refimpl_typechecks_against_published_x402_core::error TS",
        "tests/test_x402_draft_refimpl.py::test_pending_frames_refimpl_and_opens_no_pr::PR opened",
    ],
    "L16": [
        'tests/test_facilitator.py::test_l16_facilitator_exposes_supported_verify_settle::fac.supported()["scheme"] == "exact"',
        'tests/test_facilitator.py::test_l16_facilitator_exposes_supported_verify_settle::fac.supported()["network"] == "nano:live"',
        "tests/test_facilitator.py::test_l16_facilitator_exposes_supported_verify_settle::callable(fac.verify) and callable(fac.settle)",
        "tests/test_facilitator.py::test_l16_http_get_supported::r.status_code == 200",
        'tests/test_facilitator.py::test_l16_http_get_supported::body["network"] == "nano:live"',
        'tests/test_facilitator.py::test_l16_verify_confirms_on_two_independent_endpoints::["confirmedOn"] == 2',
        "tests/test_facilitator.py::test_l16_fail_closed_when_any_endpoint_errors::fail-closed",
        "tests/test_facilitator.py::test_l16_refuses_less_than_two_endpoints::fail-closed",
        "tests/test_facilitator.py::test_l16_http_post_verify_confirms_on_two_endpoints::isValid",
    ],
    "L17": [
        "tests/test_facilitator.py::test_l17_settle_re_verifies_then_claims_atomically::success",
        "tests/test_facilitator.py::test_l17_settle_never_trusts_prior_verify::unconfirmed",
        "tests/test_facilitator.py::test_l17_claim_store_persists_exactly_once_across_instances::persists",
        "tests/test_facilitator.py::test_l17_concurrent_settles_approve_exactly_once::results.count(True) == 1",
        "tests/test_facilitator.py::test_l17_http_post_settle_exactly_once::duplicate",
    ],
    "L18": [
        "tests/test_facilitator_live.py::test_live_confirms_real_send_on_two_independent_public_rpcs::res.confirmed_on == 2",
        "tests/test_facilitator_live.py::test_live_confirms_real_send_on_two_independent_public_rpcs::res.ok is True",
        "tests/test_facilitator_live.py::test_live_confirms_real_send_on_two_independent_public_rpcs::res.consulted == 2",
        "tests/test_facilitator_live.py::test_wrong_destination_refused_from_real_shape::res.ok is False",
    ],
    "L19": [
        "tests/test_httpx402.py::test_402_then_serves_after_settled_payment::first.status_code == 402",
        "tests/test_httpx402.py::test_402_then_serves_after_settled_payment::PAYMENT_REQUIRED_HEADER in first.headers",
        "tests/test_httpx402.py::test_402_then_serves_after_settled_payment::second.status_code == 200",
        "tests/test_httpx402.py::test_402_then_serves_after_settled_payment::the protected result",
        'tests/test_httpx402.py::test_402_then_serves_after_settled_payment::settle["success"] is True',
    ],
    "L20": [
        "tests/test_httpx402.py::test_spent_proof_never_serves_twice::status_code == 402",
        "tests/test_httpx402.py::test_spent_proof_never_serves_twice::the protected result",
    ],
    "L21": [
        'tests/test_paidtool.py::test_replay_is_refused_once::second["success"] is False',
        'tests/test_paidtool.py::test_replay_is_refused_once::"result" not in second',
        'tests/test_paidtool.py::test_replay_is_refused_once::first["success"] is True',
    ],
    "L22": [
        'tests/test_paidtool.py::test_execute_serves_result_after_verify_and_settle::out["result"]["data"] == "the protected tool result"',
        'tests/test_paidtool.py::test_execute_serves_result_after_verify_and_settle::out["settlement"]["success"] is True',
        'tests/test_paidtool.py::test_request_issues_one_time_payto::assert r1["pay_to"] != r2["pay_to"]',
        'tests/test_paidtool.py::test_request_issues_one_time_payto::assert r1["pay_to"].startswith("nano_")',
        'tests/test_paidtool.py::test_fail_closed_single_endpoint_refuses::out["success"] is False',
        'tests/test_paidtool.py::test_wrong_amount_is_refused::out["success"] is False',
        'tests/test_paidtool.py::test_missing_request_id_is_refused::out["success"] is False',
    ],
    "L23": [
        'tests/test_journaldb.py::test_read_nano_tx_roundtrips_evidence_rows::rows[0]["payer"] == EXT',
        "tests/test_journaldb.py::test_read_nano_tx_roundtrips_evidence_rows::ok_ext is True and ok_own is False",
        'tests/test_journaldb.py::test_journal_reader_counts_only_external_for_scorecard::[r["payer"] for r in receipts] == [EXT]',
        'tests/test_journaldb.py::test_scorecard_build_uses_real_journal_db::["nano"]["external_receipts"] == 1',
        "tests/test_journaldb.py::test_cli_journal_db_build_and_verify_is_reproducible::verify PASS",
        "tests/test_journaldb.py::test_journal_db_is_readonly_and_network_free::pytest.raises(sqlite3.OperationalError)",
    ],
}


def quote(path: str, func: str, needle: str) -> str:
    full = os.path.join(REPO, path)
    if not os.path.exists(full):
        return f"- {path}: FILE NOT FOUND\n"
    src = open(full, encoding="utf-8").read().splitlines()
    top = re.compile(rf"^(async )?def {re.escape(func)}\(")
    start = None
    for i, line in enumerate(src):
        if top.match(line.strip()):
            start = i
            break
    if start is None:
        return f"- {path}:{func}: FUNC NOT FOUND\n"
    # search the function body (until next top-level def) for a line with needle
    for j in range(start, min(len(src), start + 60)):
        if j > start and re.match(r"^(async )?def ", src[j]):
            break
        if needle in src[j]:
            return f"- {path}:{j+1}: {src[j].strip()}"
    # fall back to the def line itself
    return f"- {path}:{start+1}: def {func}(...):  (needle {needle!r} not in body)"


def main() -> str:
    lines = ["=== COMPACT EVIDENCE L0..L23 (asserting lines) ==="]
    for law_id in [f"L{i}" for i in range(24)]:
        if law_id == "L2":
            lines.append(f"## {law_id} — STUCK (no funded wallet; AGENTS forbids seeking funds; recorded not faked)")
            continue
        needles = NEEDLES.get(law_id)
        if not needles:
            continue
        lines.append(f"## {law_id}")
        for entry in needles:
            parts = entry.split("::")
            if len(parts) == 3:
                path, func, needle = parts
                lines.append(quote(path, func, needle))
    lines.append("=== pytest full-suite summary ===")
    try:
        out = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                             cwd=REPO, capture_output=True, text=True, timeout=400)
        lines.append(out.stdout[-600:])
        lines.append(f"pytest exit_code={out.returncode}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"pytest failed to run: {exc}")
    return "\n".join(lines)


if __name__ == "__main__":
    bundle = main()
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ev_compact.txt"
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(bundle)
    print(f"{dest}: {len(bundle)} bytes")
    # report any needles that did not land
    for ln in bundle.splitlines():
        if "NOT FOUND" in ln or "not in body" in ln:
            print("  WARN:", ln)