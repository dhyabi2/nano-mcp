"""Tests for block 11: prepare P1's PR-2 deliverable (x402 `exact`-on-`nano`
reference implementation draft).

The block's deliverable is an outward-facing artifact *awaiting human approval*,
so these tests observe the artifact itself (structure, semantics, and that it
type-checks against the published @x402/core and passes its own offline TS
tests), consistent with test_x402_draft.py for the block-10 spec. They never
open a PR or touch a real funded Nano wallet.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PENDING = REPO.parent / "pending.md"
DRAFT = (
    REPO
    / "draft"
    / "x402"
    / "typescript"
    / "packages"
    / "mechanisms"
    / "nano"
)
SRC = DRAFT / "src"


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def all_src() -> str:
    return "\n".join(read_file(p) for p in SRC.rglob("*.ts"))


# ---------------------------------------------------------------- structure

def test_refimpl_package_exists_at_x402_path():
    assert (DRAFT / "package.json").is_file(), f"package missing at {DRAFT}"
    for sub in ("exact/client", "exact/server", "exact/facilitator"):
        assert (SRC / f"{sub}/index.ts").is_file(), f"missing {sub}/index.ts"
    for f in ("crypto.ts", "claim.ts", "rpc.ts", "types.ts"):
        assert (SRC / f).is_file(), f"missing {f}"


def test_refimpl_package_metadata_marks_ai_agent_draft_unsubmitted():
    pkg = read_file(DRAFT / "package.json")
    assert '"name": "@x402/nano"' in pkg
    assert "Rai" in pkg
    assert "draft" in pkg.lower()
    assert "not yet submitted" in pkg.lower()


def test_refimpl_implements_the_three_core_interfaces():
    texts = {
        "client": read_file(SRC / "exact/client/index.ts"),
        "server": read_file(SRC / "exact/server/index.ts"),
        "facilitator": read_file(SRC / "exact/facilitator/index.ts"),
    }
    assert re.search(r"implements SchemeNetworkClient", texts["client"])
    assert re.search(r"implements SchemeNetworkServer", texts["server"])
    assert re.search(r"implements SchemeNetworkFacilitator", texts["facilitator"])


# ---------------------------------------------------------------- semantics

def test_refimpl_encodes_network_asset_and_64hex_proof():
    text = all_src()
    assert "nano:live" in text
    assert "XNO" in text
    assert "paymentProof" in text
    # The block hash / paymentProof is 64 uppercase hex (32 bytes).
    assert "64" in text
    assert "hex" in text.lower()


def test_refimpl_fail_closed_two_independent_rpcs():
    rpc = read_file(SRC / "rpc.ts")
    fac = read_file(SRC / "exact/facilitator/index.ts")
    flat = (rpc + fac).replace("\n", " ")
    assert "at least two" in flat.lower() or ">= 2" in flat or "two independent" in flat.lower()
    assert "fails closed" in flat.lower() or "fail closed" in flat.lower()
    assert "verifyBlockOnIndependentEndpoints" in fac  # referenced by settle too


def test_refimpl_atomic_single_use_claim():
    claim = read_file(SRC / "claim.ts")
    fac = read_file(SRC / "exact/facilitator/index.ts")
    assert "exactly once" in claim.lower() or "single-use" in claim.lower()
    assert "consumptionKey" in claim
    assert "claimStore.claim" in fac


# ---------------------------------------------------------------- subprocess (tsc + ts tests)

@pytest.fixture(scope="module")
def drafted_draft():
    """Ensure the draft package's node_modules resolve @x402/core so tsc runs."""
    if not (DRAFT / "node_modules" / "@x402" / "core").is_dir():
        r = subprocess.run(["npm", "install"], cwd=DRAFT, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise pytest.skip(f"npm install unavailable/offline: {r.stderr[-200:]}")
    return DRAFT


def test_refimpl_typechecks_against_published_x402_core(drafted_draft):
    r = subprocess.run(["npx", "--yes", "tsc", "--noEmit"], cwd=DRAFT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"tsc --noEmit failed:\n{r.stdout}\n{r.stderr}"
    assert "error TS" not in r.stdout


def test_refimpl_own_ts_tests_pass(drafted_draft):
    r = subprocess.run(["npm", "test"], cwd=DRAFT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"npm test failed:\n{r.stdout}\n{r.stderr}"
    assert "ℹ pass" in r.stdout


# ------------------------------------------------------------- pending.md framing

def test_pending_frames_refimpl_and_opens_no_pr():
    text = read_file(PENDING)
    assert "reference implementation" in text.lower() or "Reference" in text
    # The pending.md must frame the reference-implementation contribution
    # (PR 2) as following the spec (PR 1), and must NOT have opened any PR.
    assert "spec" in text.lower()
    assert "Approve so I (a) open PR 1" in text
    assert "PR 2" in text
    assert "PR opened" not in text