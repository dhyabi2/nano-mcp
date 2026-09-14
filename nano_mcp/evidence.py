"""Evidence gating: decide when a real external nano payment becomes `nano_tx`.

AGENTS.md says only REAL usage counts toward the goal, and we must never write
evidence for accounts we control. This module encapsulates that rule so the
service (and the MCP server) can journal a payment only when it arrives from an
account NOT in NANO_AGENT_OWN_ACCOUNTS.

The journal writer is injectable so tests can point at a scratch nano-pulse db
(stitched from `journal.append`) without touching the real journal, and
`should_log` is a pure function (no I/O) so the own-account rule is cheap to
unit test in both directions.
"""
from __future__ import annotations

import os
import time
from typing import Callable


def own_accounts_from_env() -> set[str]:
    """Read NANO_AGENT_OWN_ACCOUNTS (whitespace/comma separated nano_ addrs)."""
    raw = os.environ.get("NANO_AGENT_OWN_ACCOUNTS", "")
    return {tok.strip() for tok in raw.replace(",", " ").split() if tok.strip()}


def should_log(payer: str, own_accounts: set[str] | None = None) -> bool:
    """True iff `payer` is an account we do not control (external, real usage)."""
    own = own_accounts if own_accounts is not None else own_accounts_from_env()
    return payer not in own


def append_nano_tx(
    payer: str,
    amount_xno: str,
    block_hash: str,
    journal_append: Callable,
    own_accounts: set[str] | None = None,
) -> bool:
    """Append one nano_tx event iff payer is external. Returns True if logged.

    `journal_append` signature mirrors /root/.hermes/plugins/nano-pulse/journal.py:
    journal_append(db, [(ts, kind, data_dict)]).
    """
    if not should_log(payer, own_accounts):
        return False
    journal_append(
        [
            (
                time.time(),
                "nano_tx",
                {
                    "hash": block_hash,
                    "direction": "receive",
                    "external": True,
                    "amount_xno": amount_xno,
                    "url": f"https://nanexplorer.com/nano/block/{block_hash}",
                },
            )
        ]
    )
    return True