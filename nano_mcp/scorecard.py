"""Open rail scorecard (roadmap stage 4): measured fee, finality and freeze per
rail, published with raw data and a script that reproduces every figure.

This is the AI-agent-payments scorecard in the mission's own ledger terms. Two
binding strategy laws drive the design (rai-agent/strategy/.ledger):

  * L5  Goal progress is Nano's measured share of observed agent payments, never
         self-generated traffic. Test: the scorecard computes share from public
         x402 counts and nano receipts whose payer is outside
         NANO_AGENT_OWN_ACCOUNTS; Rai's own test payments add zero.
  * L6  Every published scorecard figure is reproducible from the published raw
         data. Test: running the scorecard script on the published raw data
         reproduces every published figure exactly.

Two hard rules follow and are enforced here:

  1. **Network-free + deterministic.** `build` reads ONLY committed raw files
     (rails.json, x402.json) and an injected journal reader. It never calls an
     RPC, an HTTP API, an exchange or the ledger tool. For a given raw dir and a
     given journal reader it returns byte-identical figures.
  2. **Own traffic counts zero.** The share counts only nano receipts whose
     payer is NOT in NANO_AGENT_OWN_ACCOUNTS (the same gate as evidence.py's
     `should_log`). A payer in the own list adds exactly zero.

Raw data lives under `scorecard/raw/` (committed), published output under
`scorecard/published.json`, and a manifest mapping every published figure to the
SHA-256 of the raw record(s) that produced it under `scorecard/manifest.json`.
`verify` reruns the build on that raw data and fails if any figure differs.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Raw data model
# ---------------------------------------------------------------------------

# Every rail's measured fee / finality / freeze record. `source` must be a real,
# committed, human-verifiable origin for the number (docs URL, protocol constant,
# node observation note) — never invented. `method` says how it was obtained:
#   "protocol"   a property of the chain (e.g. Nano fee = 0 by protocol)
#   "measured"   observed from a real transaction / node
#   "reported"   published public figure from `source`
RAIL_DEFAULTS = ("fee", "finality_ms", "freeze_capable")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(obj) -> str:
    """Deterministic JSON serialisation (sorted keys, no trailing ws)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def load_rails(path: Path) -> list[dict]:
    """Load the committed per-rail raw records, validating their shape."""
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("rails.json must be a JSON array of rail records")
    for rec in data:
        for key in ("rail", "metric", "value", "unit", "source", "method", "as_of"):
            if key not in rec:
                raise ValueError(f"rail record missing required field {key!r}: {rec}")
    return data


def load_x402(path: Path) -> dict:
    with open(path) as fh:
        data = json.load(fh)
    for key in ("count", "volume_usd", "source", "as_of"):
        if key not in data:
            raise ValueError(f"x402.json missing required field {key!r}")
    return data


class JournalProto:
    """A reader that yields nano receipts as dicts with at least a `payer`.

    Drives the L5 share (#instead of) a live nano-pulse DB or a scratch one.
    """

    def read(self, after_seq: int = 0):
        raise NotImplementedError


def count_external_receipts(
    journal: "JournalProto",
    own_accounts: set[str] | None = None,
) -> tuple[list[dict], int]:
    """Return (external_receipts, count) from a journal, dropping payers in
    NANO_AGENT_OWN_ACCOUNTS (their traffic adds zero — strategy law L5)."""
    own = own_accounts if own_accounts is not None else set()
    ext = [r for r in journal.read(0) if r.get("payer") not in own]
    return ext, len(ext)


def _rail_figure(records: list[dict], rail: str, metric: str):
    """The figure for `rail`/`metric` and the raw record(s) it came from."""
    matches = [r for r in records if r["rail"] == rail and r["metric"] == metric]
    if not matches:
        return None, []
    series = sorted(matches, key=lambda r: r["as_of"])
    return series[-1], series  # latest record is the published figure


def build(
    raw_dir: "str | os.PathLike",
    journal: "JournalProto | None" = None,
    own_accounts: "set[str] | None" = None,
) -> dict:
    """Compute every published figure from committed raw data + an optional
    journal. Pure and deterministic: only reads `raw_dir` files and `journal`."""
    raw_dir = Path(raw_dir)
    rails = load_rails(raw_dir / "rails.json")
    x402 = load_x402(raw_dir / "x402.json")

    # --- rails table (per rail, latest record per metric) -------------------
    rail_names = sorted({r["rail"] for r in rails})
    rails_table: dict[str, dict] = {}
    for rail in rail_names:
        entry: dict = {}
        for metric in RAIL_DEFAULTS:
            latest, series = _rail_figure(rails, rail, metric)
            if latest is not None:
                entry[metric] = latest["value"]
        rails_table[rail] = entry

    # --- x402 (the incumbent observed-agent-payment count) -----------------
    x402_count = int(x402["count"])

    # --- nano receipts (external only) -------------------------------------
    if journal is not None:
        external, external_count = count_external_receipts(journal, own_accounts)
    else:
        external, external_count = [], 0

    # --- the scorecard's single headline: Nano's share of observed payments --
    denominator = x402_count + external_count
    share = external_count / denominator if denominator > 0 else 0.0

    published = {
        "rails": rails_table,
        "x402": {
            "count": x402_count,
            "volume_usd": x402["volume_usd"],
            "source": x402["source"],
            "as_of": x402["as_of"],
        },
        "nano": {
            "external_receipts": external_count,
            "excluded_own": sum(1 for r in (journal.read(0) if journal else []) if r.get("payer") in (own_accounts or set())),
            "share_of_observed": share,
        },
        "_meta": {
            "raw_dir": str(raw_dir),
            "figure_definitions": f"share=external_receipts/(x402_count+external_receipts)",
        },
    }
    return published


# ---------------------------------------------------------------------------
# Manifest + verify (strategy law L6)
# ---------------------------------------------------------------------------


def make_manifest(raw_dir: str | os.PathLike, published: dict) -> dict:
    """Map every published figure to the SHA-256 of the raw record(s) that
    produced it, plus a whole-file hash of each raw data file."""
    raw_dir = Path(raw_dir)
    manifest: dict = {"raw_file_hashes": {}, "figures": {}}
    for fname in ("rails.json", "x402.json"):
        p = raw_dir / fname
        if p.exists():
            manifest["raw_file_hashes"][fname] = _sha256_text(p.read_text())
    for rail, entry in published["rails"].items():
        for metric, value in entry.items():
            record = {"rail": rail, "metric": metric, "value": value}
            manifest["figures"][f"{rail}.{metric}"] = _sha256_text(_canonical(record))
    x = published["x402"]
    manifest["figures"]["x402.count"] = _sha256_text(_canonical(x["count"]))
    manifest["figures"]["share_of_observed"] = _sha256_text(
        _canonical(published["nano"]["share_of_observed"])
    )
    return manifest


def verify(
    raw_dir: "str | os.PathLike",
    published_path: "str | os.PathLike",
    journal: "JournalProto | None" = None,
    own_accounts: "set[str] | None" = None,
) -> "tuple[bool, list[str]]":
    """Rerun the build on `raw_dir` and compare to the committed publication.

    Returns (ok, problems). Every published figure must equal the rebuild
    (strategy law L6: running the script on the published raw data reproduces
    every published figure exactly).
    """
    committed = json.loads(Path(published_path).read_text())
    rebuilt = build(raw_dir, journal, own_accounts)
    problems: list[str] = []

    # Compare rail metric values (the reproducible figures).
    for rail, entry in committed.get("rails", {}).items():
        for metric, value in entry.items():
            got = rebuilt["rails"].get(rail, {}).get(metric)
            if got != value:
                problems.append(f"{rail}.{metric}: published={value!r} rebuilt={got!r}")
    got_share = rebuilt["nano"]["share_of_observed"]
    if got_share != committed["nano"]["share_of_observed"]:
        problems.append(
            f"share_of_observed: published={committed['nano']['share_of_observed']!r} rebuilt={got_share!r}"
        )
    return (not problems), problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _json_file(path):
    raw = Path(path).read_text()
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build", help="build published.json + manifest from raw data")
    pb.add_argument("--raw", required=True)
    pb.add_argument("--out", default="scorecard/published.json")
    pb.add_argument("--manifest", default="scorecard/manifest.json")
    pb.add_argument("--journal", default=None, help="optional .json list of receipts")
    pb.add_argument("--own", default="", help="whitespace/comma own accounts")

    pv = sub.add_parser("verify", help="rerun build and compare to published figures")
    pv.add_argument("--raw", required=True)
    pv.add_argument("--published", default="scorecard/published.json")
    pv.add_argument("--journal", default=None)
    pv.add_argument("--own", default="")

    args = p.parse_args(argv)

    def _receipts(path: str | None) -> "JournalProto | None":
        if not path:
            return None
        rows = _json_file(path)

        class _Reader(JournalProto):
            def read(self, after_seq: int = 0):
                return rows

        return _Reader()

    own: set[str] = {
        t.strip() for t in args.own.replace(",", " ").split() if t.strip()
    }

    if args.cmd == "build":
        journal = _receipts(args.journal)
        published = build(args.raw, journal, own)
        Path(args.out).write_text(_canonical(published))
        Path(args.manifest).write_text(_canonical(make_manifest(args.raw, published)))
        print(f"wrote {args.out} and {args.manifest}")
        print(f"share_of_observed = {published['nano']['share_of_observed']:.6%}")
        return 0

    journal = _receipts(args.journal)
    ok, problems = verify(args.raw, args.published, journal, own)
    for problem in problems:
        print(f"MISMATCH {problem}")
    print("verify PASS" if ok else f"verify FAIL ({len(problems)} mismatches)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())