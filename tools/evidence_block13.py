#!/usr/bin/env python3
"""Consolidated evidence for `ledger verify --block 13` (L18).

Modeled on evidence_block12.py. For block 13's law L18 quotes the strictest
assertions from its dedicated test file plus a fresh pytest tail. Block 13 law:

  L18 — the multi-RPC verifier parses the REAL Nano block_info shape and
        confirms a real on-chain send on two independent public endpoints.

Usage: python3 tools/evidence_block13.py OUT_FILE
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
T = TESTS / "test_facilitator_live.py"


def quote(needle: str) -> str:
    text = T.read_text(encoding="utf-8")
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return f"(needle {needle!r} not found in {T.name})"


LAW_PROOF = {
    "L18": [
        quote("def test_normalize_parses_real_nano_block_info_shape"),
        quote('nb.account == REAL_PAYER'),
        quote('nb.destination == REAL_PAYTO'),
        quote('nb.confirmed is True'),
        quote("def test_normalize_accepts_stub_shape_and_bool_confirmed"),
        quote("def test_normalize_rejects_missing_confirmed"),
        quote("def test_incomplete_node_response_is_refused_not_passed"),
        quote("assert \"missing 'confirmed'\" in (res.reason or \"\")"),
        quote("def test_live_confirms_real_send_on_two_independent_public_rpcs"),
        quote('res.confirmed_on == 2'),
        quote('send["payer"] == REAL_PAYER'),
        quote('send["receiver"] == REAL_PAYTO'),
        quote('send["amount"] == REAL_AMOUNT'),
        quote("REAL_BLOCK = "),
        quote("REAL_PAYER = "),
    ],
}


def pytest_tail() -> str:
    res = subprocess.run(
        [sys.executable, "-m", "pytest", str(T), "-q"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return " ".join((res.stdout + res.stderr).strip().splitlines()[-1:])


FULL_SUITE = subprocess.run(
    [sys.executable, "-m", "pytest", "-m", "not network", "-q"],
    capture_output=True,
    text=True,
    cwd=ROOT,
).stdout.strip().splitlines()[-1:]


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/evidence_block13.txt"
    lines = ["# Evidence for `ledger verify --block 13` (L18)", ""]
    for law, excerpts in LAW_PROOF.items():
        lines.append(f"## {law}")
        for e in excerpts:
            lines.append(f"- {e}")
        lines.append("")
    lines.append("## fresh pytest tail (tests/test_facilitator_live.py)")
    lines.append(f"- {pytest_tail()}")
    lines.append("")
    lines.append("## full offline suite tail")
    trailer = FULL_SUITE[-1] if FULL_SUITE else "(no output)"
    lines.append(f"- {trailer}")
    text = "\n".join(lines) + "\n"
    Path(out).write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text)} bytes)")
    print(text)


if __name__ == "__main__":
    main()