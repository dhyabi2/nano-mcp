"""Exactly-once approval store for the nano-mcp pay-per-call server.

The brainstorm (see .ledger/PLAN.md block 4) converged on using a SQLite-backed
`INSERT ... PRIMARY KEY` as a *claiming lock*: approving a request_id is an
atomic insert that succeeds exactly once, so the same payment can never authorize
two calls, even across server restarts or under concurrency. A payment whose
request has already been approved is refused (replay-safe).

The on-chain check itself (does a matching send to the one-time address exist?)
lives in the server's verify step; this store *records* the approval once.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    request_id  TEXT PRIMARY KEY,
    tx_hash     TEXT,
    status      TEXT NOT NULL,
    paid_addr   TEXT,
    amount_raw  TEXT,
    approved_at REAL
);
"""


class ApprovalStore:
    """Persistent exactly-once record of approved request_ids."""

    def __init__(self, path: str | None = None):
        # default: a store next to the package so approvals survive restarts.
        self.path = path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "approvals.db"
        )
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def _row(self, request_id: str) -> tuple | None:
        with closing(self._conn.execute(
            "SELECT tx_hash, status, paid_addr, amount_raw, approved_at FROM approvals WHERE request_id=?",
            (request_id,),
        )) as cur:
            return cur.fetchone()

    def is_approved(self, request_id: str) -> bool:
        row = self._row(request_id)
        return row is not None and row[1] == "approved"

    def claim(
        self,
        request_id: str,
        tx_hash: str,
        paid_addr: str,
        amount_raw: int,
    ) -> bool:
        """Atomically mark request_id as approved. Returns True only on the first
        (and only) success; returns False if it was already approved."""
        with self._lock:
            try:
                with closing(self._conn.execute(
                    "INSERT INTO approvals (request_id, tx_hash, status, paid_addr, amount_raw, approved_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (request_id, tx_hash, "approved", paid_addr, str(amount_raw), __import__("time").time()),
                )) as cur:
                    ...
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                # already claimed -> replay refused
                return False

    def get(self, request_id: str) -> dict | None:
        row = self._row(request_id)
        if row is None:
            return None
        return {
            "tx_hash": row[0],
            "status": row[1],
            "paid_addr": row[2],
            "amount_raw": int(row[3]) if row[3] else 0,
            "approved_at": row[4],
        }
