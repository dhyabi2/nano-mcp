#!/usr/bin/env python3
"""Consolidated evidence for `ledger verify --block 12` (L16, L17).

Modeled on evidence_block11.py. For each law minted in block 12 quotes the
strictest assertion from its dedicated test plus a fresh pytest tail of the
block's test file and the full offline suite. Block 12's own laws:

  L16 — the facilitator exposes /supported /verify /settle per the exact-on-nano
        spec and fails closed unless a proof confirms on at least two independent
        RPC endpoints (strategy law L1).
  L17 — settle re-verifies on-chain then binds a proof to its request with an
        atomic single-use claim, so one proof settles exactly once.

Usage: python3 tools/evidence_block12.py OUT_FILE
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
T = TESTS / "test_facilitator.py"


def quote(name: str, needle: str) -> str:
    text = T.read_text(encoding="utf-8")
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return f"(needle {needle!r} not found in {T.name})"


def pytest_tail(patterns) -> str:
    res = subprocess.run(
        [sys.executable, "-m", "pytest", str(T), "-q"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    tail = (res.stdout + res.stderr).strip().splitlines()[-1:]
    return " ".join(tail)


LAW_PROOF = {
    "L16": [
        quote("test_l16_facilitator_exposes_supported_verify_settle", "def test_l16_facilitator_exposes"),
        quote("test_l16_verify_confirms_on_two_independent_endpoints", 'extra"]["confirmedOn"]'),
        quote("test_l16_fail_closed_when_any_endpoint_errors", "fail-closed: the healthy endpoint"),
        quote("test_l16_refuses_less_than_two_endpoints", '"fail-closed" in res["invalidMessage"]'),
        quote("test_l16_http_get_supported", 'body["network"]'),
        quote("test_l16_http_post_verify_confirms_on_two_endpoints", 'r.json()["isValid"] is True'),
    ],
    "L17": [
        quote("test_l17_settle_re_verifies_then_claims_atomically", 's1["success"] is True'),
        quote("test_l17_settle_re_verifies_then_claims_atomically", 's2["errorReason"] == "duplicate"'),
        quote("test_l17_settle_never_trusts_prior_verify", 's["errorReason"] == "unconfirmed"'),
        quote("test_l17_claim_store_persists_exactly_once_across_instances", "c2.claim(key) is False"),
        quote("test_l17_concurrent_settles_approve_exactly_once", "results.count(True) == 1"),
        quote("test_l17_http_post_settle_exactly_once", 's2["errorReason"] == "duplicate"'),
    ],
}

FULL_SUITE = subprocess.run(
    [sys.executable, "-m", "pytest", "-m", "not network", "-q"],
    capture_output=True,
    text=True,
    cwd=ROOT,
).stdout.strip().splitlines()[-1:]


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/evidence_block12.txt"
    lines = ["# Evidence for `ledger verify --block 12` (L16, L17)", ""]
    for law, excerpts in LAW_PROOF.items():
        lines.append(f"## {law}")
        for e in excerpts:
            lines.append(f"- {e}")
        lines.append("")
    lines.append("## fresh pytest tail (tests/test_facilitator.py)")
    lines.append(f"- {pytest_tail(LAW_PROOF)}")
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