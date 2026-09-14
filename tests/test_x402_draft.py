"""Tests for block 10: prepare P1's deliverable (x402 `exact`-on-`nano` spec draft).

The block's deliverable is an outward-facing artifact *awaiting human approval*, so
these tests observe the artifact itself (its path, structure and self-consistency
against x402's scheme conventions) rather than network behavior. They exist so the
block's law has a real, runnable test.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = (
    REPO
    / "draft"
    / "x402"
    / "specs"
    / "schemes"
    / "exact"
    / "scheme_exact_nano.md"
)
PENDING = REPO.parent / "pending.md"

REQUIRED_SECTIONS = [
    "# Scheme: `exact` on `Nano`",
    "## Supported Networks",
    "## Summary",
    "## Payment flow",
    "## `PaymentRequirements`",
    "## PaymentPayload `payload` Field",
    "## `SettlementResponse`",
    "## Facilitator Verification Rules",
    "## Settlement Logic",
    "## Failure disposition",
]


def extract_json_blocks(text: str):
    """Yield (section_hint, parsed) for each ```json ... ``` fenced block."""
    for m in re.finditer(r"```json\n(.*?)\n```", text, re.DOTALL):
        try:
            yield json.loads(m.group(1))
        except json.JSONDecodeError as e:  # pragma: no cover (guard aid)
            raise AssertionError(f"spec has an invalid JSON block: {e}") from e


def test_spec_file_exists_at_x402_path():
    assert SPEC.is_file(), f"spec draft missing at {SPEC}"


def test_spec_has_all_required_sections():
    text = SPEC.read_text()
    for sec in REQUIRED_SECTIONS:
        assert sec in text, f"spec is missing section {sec!r}"


def test_spec_payload_uses_nano_proof_and_network():
    text = SPEC.read_text()
    assert '"network": "nano:live"' in text
    assert '"asset": "XNO"' in text
    assert '"paymentProof"' in text
    assert '"scheme": "exact"' in text


def test_spec_json_blocks_parse_and_are_self_consistent():
    text = SPEC.read_text()
    blocks = list(extract_json_blocks(text))
    assert len(blocks) >= 4, "expected requirements, payload, and response examples"
    # The accepted.network and asset must match across examples.
    for b in blocks:
        if "accepted" in b:
            acc = b["accepted"]
            assert acc["network"] == "nano:live"
            assert acc["asset"] == "XNO"
            assert acc["scheme"] == "exact"
    # At least one block is the full PaymentPayload with a paymentProof.
    full = [b for b in blocks if "payload" in b and "paymentProof" in b.get("payload", {})]
    assert full, "no Payload example carrying paymentProof"
    proof = full[0]["payload"]["paymentProof"]
    assert re.fullmatch(r"[0-9A-F]{64}", proof), "paymentProof must be a 64-char uppercase hex block hash"


def test_spec_encodes_strategy_law_l1_two_independent_rpcs():
    text = SPEC.read_text()
    flat = text.replace("\n", " ").replace("*", "")
    assert "at least two independent" in flat and "RPC endpoints" in flat
    assert "fail closed" in text.lower()  # single-RPC outage never approves


def test_spec_encodes_single_use_claim():
    text = SPEC.read_text()
    assert "claim" in text.lower() and "exactly once" in text.lower()


def test_pending_p1_framed_as_exact_scheme_on_nano_network():
    assert PENDING.is_file(), f"pending.md missing at {PENDING}"
    text = PENDING.read_text()
    # The framing correction from block 10: Nano is a network under `exact`.
    assert "exact` scheme on the `nano` network" in text
    assert "scheme_exact_nano.md" in text  # correct x402 spec path
    assert "New Chains" in text


def test_no_upstream_pr_opened_by_default():
    """AGENTS blocks opening upstream PRs without human approval; the block must not."""
    text = PENDING.read_text()
    # The Ask still requires approval; nothing should claim a PR was already opened.
    assert "I can open PR 1" not in text or "Approve so I (a) open PR 1" in text
    assert "PR opened" not in text or "requiring approval" in text