"""Block 8 tests: open rail scorecard (roadmap stage 4).

L12 (share): Nano's scorecard share comes only from public x402 counts plus nano
receipts whose payer is outside NANO_AGENT_OWN_ACCOUNTS; Rai's own test payments
add exactly zero.
L13 (reproducibility): every published scorecard figure is reproduced exactly by
rerunning the scorecard build on the published raw data.

Tests are offline and deterministic: build() reads only the committed raw dir and
an injected journal reader, never the live node.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nano_mcp.evidence import append_nano_tx, own_accounts_from_env
from nano_mcp.scorecard import (
    JournalProto,
    build,
    count_external_receipts,
    load_rails,
    load_x402,
    make_manifest,
    verify,
)

RAW = Path(__file__).parent.parent / "scorecard" / "raw"

OWN1 = "nano_1ownw7b6xjyha7m13objpn5ubkquzd6ska8kwopzf1ecbfmn35d1zey3aa"
OWN2 = "nano_1ownq8c9drxe1n4xk7m5q2af4d9xy7e5qaqcd94ka1cq1br49kcm1j7v8u4bb"
EXT = "nano_3extzzzzn4xk7m5q2af4d9xy7e5qaqcd94ka1cq1br49kcm1j9abcdefgh"


class FakeJournal(JournalProto):
    def __init__(self, rows):
        self._rows = rows

    def read(self, after_seq: int = 0):
        return self._rows


def _own():
    return {OWN1, OWN2}


def test_raw_data_is_committed_and_valid():
    rails = load_rails(RAW / "rails.json")
    x402 = load_x402(RAW / "x402.json")
    names = {r["rail"] for r in rails}
    assert "nano" in names and "x402_usdc_base" in names and "card_networks" in names
    assert x402["count"] > 0
    metrics = {(r["rail"], r["metric"]) for r in rails}
    for rail in names:
        for m in ("fee", "finality_ms", "freeze_capable"):
            assert (rail, m) in metrics, f"{rail}.{m} missing"


def test_l12_share_counts_only_external_receipts():
    j = FakeJournal([
        {"payer": EXT, "hash": "A" * 64, "amount_xno": "0.001"},
        {"payer": OWN1, "hash": "B" * 64, "amount_xno": "0.001"},  # own -> zero
    ])
    published = build(RAW, j, _own())
    # denominator = public x402 count + external receipts ONLY
    assert published["nano"]["external_receipts"] == 1
    assert published["nano"]["excluded_own"] == 1
    expected_share = 1 / (165_000_000 + 1)
    assert published["nano"]["share_of_observed"] == pytest.approx(expected_share)


def test_l12_own_traffic_adds_exactly_zero_to_share():
    only_own = FakeJournal([{"payer": OWN1, "hash": "C" * 64, "amount_xno": "0.01"}])
    empty = FakeJournal([])
    p_own = build(RAW, only_own, _own())
    p_empty = build(RAW, empty, _own())
    # own traffic must not shift the share at all
    assert p_own["nano"]["external_receipts"] == 0
    assert p_own["nano"]["share_of_observed"] == p_empty["nano"]["share_of_observed"] == 0.0


def test_l12_share_rises_with_each_external_receipt():
    j1 = FakeJournal([{"payer": EXT, "hash": "D" * 64, "amount_xno": "0.01"}])
    j2 = FakeJournal(
        [
            {"payer": EXT, "hash": "D" * 64, "amount_xno": "0.01"},
            {"payer": EXT, "hash": "E" * 64, "amount_xno": "0.02"},
        ]
    )
    s1 = build(RAW, j1, _own())["nano"]["share_of_observed"]
    s2 = build(RAW, j2, _own())["nano"]["share_of_observed"]
    assert s2 > s1


def test_count_external_receipts_uses_evidence_gate_semantics():
    receipts, n = count_external_receipts(
        FakeJournal([{"payer": OWN1}, {"payer": EXT}]), _own()
    )
    assert [r["payer"] for r in receipts] == [EXT]
    assert n == 1


def test_l13_verify_passes_on_published_raw_data():
    # committed raw data with an injected journal => build == verify
    j = FakeJournal([{"payer": EXT, "hash": "F" * 64, "amount_xno": "0.001"}])
    published = build(RAW, j, _own())
    ok, problems = verify(RAW, _write_published(published), j, _own())
    assert ok, problems
    assert problems == []


def test_l13_verify_detects_figure_drift(tmp_path):
    # tamper with a raw rail figure => verify must fail (reproducibility law)
    j = FakeJournal([{"payer": EXT, "hash": "F" * 64, "amount_xno": "0.001"}])
    published = build(RAW, j, _own())
    published["rails"]["nano"]["fee"] = 999  # corrupt the committed publication
    ok, problems = verify(RAW, _write_published(published), j, _own())
    assert ok is False
    assert any("nano.fee" in p for p in problems)


def test_manifest_maps_figures_to_raw_hashes(tmp_path):
    j = FakeJournal([{"payer": EXT, "hash": "F" * 64, "amount_xno": "0.001"}])
    published = build(RAW, j, _own())
    manifest = make_manifest(RAW, published)
    assert "raw_file_hashes" in manifest and "figures" in manifest
    assert "nano.fee" in manifest["figures"]
    assert "share_of_observed" in manifest["figures"]
    # raw file hashes must actually point at the committed files
    import hashlib

    assert manifest["raw_file_hashes"]["rails.json"] == hashlib.sha256(
        (RAW / "rails.json").read_bytes()
    ).hexdigest()


def _write_published(published: dict, path: Path | None = None):
    path = path or (Path(__file__).parent / "_tmp_published.json")
    path.write_text(json.dumps(published, sort_keys=True))
    return path


def test_cli_build_and_verify_is_reproducible(tmp_path):
    # end-to-end: `python -m nano_mcp.scorecard build` then `verify`
    receipts = tmp_path / "receipts.json"
    receipts.write_text(json.dumps([{"payer": EXT, "hash": "F" * 64, "amount_xno": "0.001"}]))
    out = tmp_path / "published.json"
    manifest = tmp_path / "manifest.json"

    env = dict(os.environ)
    r = subprocess.run(
        [
            sys.executable, "-m", "nano_mcp.scorecard", "build",
            "--raw", str(RAW), "--out", str(out), "--manifest", str(manifest),
            "--journal", str(receipts), "--own", f"{OWN1} {OWN2}",
        ],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    assert out.exists() and manifest.exists()

    # verify succeeds against the just-written published figures
    rv = subprocess.run(
        [
            sys.executable, "-m", "nano_mcp.scorecard", "verify",
            "--raw", str(RAW), "--published", str(out),
            "--journal", str(receipts), "--own", f"{OWN1} {OWN2}",
        ],
        capture_output=True, text=True, env=env,
    )
    assert rv.returncode == 0, rv.stdout + rv.stderr
    assert "verify PASS" in rv.stdout


def test_build_is_network_free_and_deterministic():
    import nano_mcp.scorecard as sc

    # scorecard module must not import httpx / requests (no network calls)
    src = open(sc.__file__).read()
    assert "httpx" not in src
    assert "requests" not in src

    j = FakeJournal([{"payer": EXT, "hash": "F" * 64, "amount_xno": "0.001"}])
    a = build(RAW, j, _own())
    b = build(RAW, j, _own())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)  # deterministic