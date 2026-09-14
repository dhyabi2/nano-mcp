#!/usr/bin/env python3
"""Build a compact, grounded evidence bundle for `ledger verify --block 10` (L14).

Block 10's deliverable is the prepared x402 `exact`-on-`nano` spec draft (an
outward-facing artifact awaiting human approval), so the proof is structural:
the draft file exists at the real x402 spec path, has every required section,
its JSON examples parse and agree on network=asset=scheme, it encodes the
strategy's at-least-two-independent-RPC + fail-closed + exactly-once rules, and
pending.md frames the contribution as the `exact` scheme on the `nano` network
without opening a PR. A fresh pytest run of tests/test_x402_draft.py proves all
of this concretely.

Usage: python3 tools/evidence_block10.py OUT_FILE
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = (
    ROOT
    / "draft"
    / "x402"
    / "specs"
    / "schemes"
    / "exact"
    / "scheme_exact_nano.md"
)


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    parts = [f"# Block 10 evidence (L14) — {SPEC.relative_to(ROOT)}"]

    # 1. The artifact itself
    parts.append(f"=== draft exists: {SPEC.is_file()} ===")
    if SPEC.is_file():
        st = SPEC.stat()
        parts.append(f"size={st.st_size} bytes, first line: {SPEC.read_text().splitlines()[0]!r}")

    # 2. The dedicated test file (proves via assertions)
    parts.append("=== tests/test_x402_draft.py (the law's dedicated test) ===")
    tf = ROOT / "tests" / "test_x402_draft.py"
    with open(tf) as f:
        src = f.read()
    parts.append(src[:8000])

    # 3. pending.md framing (P1 must be exact-on-nano, must NOT open a PR)
    pm = ROOT.parent / "pending.md"
    parts.append("=== pending.md (outward-facing proposal framing) ===")
    if pm.is_file():
        txt = pm.read_text()
        parts.append("[exact` scheme on the `nano` network]: " + str("exact` scheme on the `nano` network" in txt))
        parts.append("[mentions new P1 with spec path]: " + str("scheme_exact_nano.md" in txt))
        parts.append("---")
        parts.append(txt[:3000])

    # 4. Fresh pytest -v of the block's test file
    parts.append("=== pytest -v tests/test_x402_draft.py (fresh run) ===")
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "tests/test_x402_draft.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    parts.append(run.stdout[-4000:])
    if run.returncode:
        parts.append("STDERR:\n" + run.stderr[-1500:])

    out.write_text("\n\n".join(parts))
    print(f"wrote {out} ({out.stat().st_size} bytes), pytest rc={run.returncode}")
    return 0 if run.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())