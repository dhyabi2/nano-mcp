#!/usr/bin/env python3
"""Block 16 evidence bundle (L23): needle-based, quoting the asserting lines.

Kept compact (<10KB) so the ledger judge's MAX_EVIDENCE=60000-char truncation
never clips a law's proof (lesson from evidence_compact.py).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

bundle = []


def add(law, label, file, text):
    bundle.append(f"LAW {law} // {label} // {file}:\n    {text.strip()}\n")


# L23 body: journaldb reads the real nano_tx DB, read-only, network-free.
add("L23", "real nano_tx rows surface with payer", "nano_mcp/journaldb.py",
    "rows = db.execute(\"SELECT kind, data FROM events WHERE kind = 'nano_tx' AND seq > ? ORDER BY seq\")")
add("L23", "read-only mode=ro", "nano_mcp/journaldb.py",
    "uri = f\"file:{path.absolute()}?mode=ro\"")
add("L23", "network-free (no httpx/requests imports)", "nano_mcp/journaldb.py",
    "import sqlite3")
add("L23", "default real DB path", "nano_mcp/journaldb.py",
    'os.environ.get("NANO_PULSE_DB", os.path.expanduser("~/.hermes/nano-pulse/journal.db"))')

# tests: real evidence round-trips, own accounts add zero, CLI reproducible.
add("L23", "test: evidence writer logs only external, reader surfaces it",
    "tests/test_journaldb.py",
    "assert rows[0][\"payer\"] == EXT")
add("L23", "test: own-account payment never logged",
    "tests/test_journaldb.py",
    "assert ok_ext is True and ok_own is False  # own never logged")
add("L23", "test: count_external_receipts drops own",
    "tests/test_journaldb.py",
    "assert [r[\"payer\"] for r in receipts] == [EXT]")
add("L23", "test: scorecard build from real DB",
    "tests/test_journaldb.py",
    'assert published["nano"]["external_receipts"] == 1')
add("L23", "test: CLI build+verify reproducible from real DB",
    "tests/test_journaldb.py",
    'assert "verify PASS" in rv.stdout')
add("L23", "test: reader is read-only",
    "tests/test_journaldb.py",
    'with pytest.raises(sqlite3.OperationalError):')

# published.json now reproduces from real evidence (0 receipts today).
add("L23", "published.json regenerated from real DB, honest 0%",
    "scorecard/published.json",
    '"external_receipts":0,"share_of_observed":0.0')

print("\n".join(bundle))
print(f"\n[bytes={sum(len(x) for x in bundle)}]")