"""Real nano-pulse journal reader for the open rail scorecard.

`evidence.append_nano_tx` journals a real external nano payment as a `nano_tx`
event in the append-only SQLite journal at `/root/.hermes/nano-pulse/journal.db`
(shared writer `journal.append`, see /root/.hermes/plugins/nano-pulse/journal.py).
Before this module existed the scorecard could only read a *hand-written* JSON
array for its ``--journal`` path, so strategy law L5's "measured share from nano
receipts" could not be computed from the actual evidence store.

This module is the missing link: a `JournalProto` adapter that reads the real
journal DB (kind=`nano_tx` events, parseable `payer`/`amount_xno`/`hash`) and
feeds the exact rows the scorecard already consumes. It is stdlib-only
(sqlite3, json), read-only and network-free, so it preserves the scorecard's
"pure + deterministic given committed raw data and a journal reader" guarantee
(strategy law L6).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


def default_journal_db() -> str:
    """Path of the real nano-pulse journal (respecting NANO_PULSE_DB)."""
    return os.environ.get(
        "NANO_PULSE_DB", os.path.expanduser("~/.hermes/nano-pulse/journal.db")
    )


def read_nano_tx(db_path, after_seq: int = 0) -> list[dict]:
    """Read real ``nano_tx`` receipt rows as dicts the scorecard can sum.

    Returns one dict per journal event with kind == ``nano_tx`` and seq >
    ``after_seq``, oldest first, in the shape the scorecard's
    ``count_external_receipts`` expects: ``{payer, hash, amount_xno, ...}``.
    Read-only (``mode=ro``) and deterministic for a fixed DB snapshot.
    """
    path = Path(db_path)
    uri = f"file:{path.absolute()}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        rows = db.execute(
            "SELECT kind, data FROM events "
            "WHERE kind = 'nano_tx' AND seq > ? ORDER BY seq",
            (after_seq,),
        ).fetchall()
    finally:
        db.close()
    out: list[dict] = []
    for kind, data_json in rows:
        data = json.loads(data_json)
        rec = {
            "payer": data.get("payer"),
            "hash": data.get("hash"),
            "amount_xno": data.get("amount_xno"),
            "direction": data.get("direction"),
            "external": bool(data.get("external")),
        }
        rec = {k: v for k, v in rec.items() if v is not None}
        out.append(rec)
    return out


def PulseJournalReader(db_path=None):  # noqa: N802 - factory keeps JournalProto seam
    """A ``JournalProto``-compatible reader for the scorecard.

    Returned object satisfies the ``JournalProto`` protocol structurally
    (a ``read(after_seq=0) -> list[dict]`` method), so the scorecard takes it
    without an import dependency on this module.
    """

    class _Reader:
        def __init__(self, path):
            self._path = path

        def read(self, after_seq: int = 0) -> list[dict]:
            return read_nano_tx(self._path, after_seq)

    return _Reader(db_path or default_journal_db())