"""Pay-per-call service: quote + verify_payment using one-time addresses.

Flow (the invention):
  1. `quote(price_raw)` derives a fresh one-time address from the server master
     key + a new request_id and returns {request_id, address, price_raw}.
  2. The agent sends exactly `price_raw` to that address via its SDK wallet.
  3. `verify_payment(request_id, amount_raw)` watches the *on-chain* state of
     that one-time address (account_history) and approves the call only once a
     matching send is confirmed there, and never twice (exactly-once).

No memo, no trusted verifier, no off-chain settlement: the chain itself is the
verifier, and the one-time address binds exactly one payment to exactly one call.

The client is injectable (an RpcClient by default; a stub in unit tests) so the
on-chain lookup and the exactly-once approval can be tested without moving funds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nano_sdk.client import RpcClient
from nano_sdk.units import raw_to_nano

from .oneshot import derive_one_time_account, new_request_id
from .store import ApprovalStore


@dataclass
class Quote:
    request_id: str
    address: str
    price_raw: int

    def as_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "address": self.address,
            "price_raw": str(self.price_raw),
            "price_nano": str(raw_to_nano(self.price_raw)),
        }


class HistoryClient(Protocol):
    """Minimal RPC surface the payment service needs (enables stub clients)."""

    def account_history(self, account: str, count: int = 20) -> dict: ...


class PaymentService:
    def __init__(
        self,
        master_secret: bytes,
        client: HistoryClient | None = None,
        store: ApprovalStore | None = None,
    ):
        self.master_secret = master_secret
        self.client = client if client is not None else RpcClient()
        self.store = store if store is not None else ApprovalStore()

    def one_time_account(self, request_id: str):
        return derive_one_time_account(self.master_secret, request_id)

    def quote(self, price_raw: int, request_id: str | None = None) -> Quote:
        rid = request_id or new_request_id()
        acct = self.one_time_account(rid)
        return Quote(request_id=rid, address=acct.address, price_raw=int(price_raw))

    def _onchain_paid(self, account, amount_raw: int) -> str | None:
        """Return the tx hash of a confirmed on-chain send *to* `account` of at
        least `amount_raw`, from the account's history; None if not yet seen.

        account_history on the (one-time) account lists sends where it is the
        source and receives where it is the destination. A payment to the
        one-time address appears as a `receive` entry (or, pre-receive, we also
        accept the matching `send` observed via `pending`). For correctness we
        require the destination to be the one-time address.
        """
        try:
            hist = self.client.account_history(account.address, count=20)
        except Exception:
            return None
        for entry in hist.get("history", []):
            etype = entry.get("type")
            amt = int(entry.get("amount", "0") or 0)
            if amt >= amount_raw:
                # receive: funds landed on this one-time address
                if etype == "receive":
                    return entry.get("hash")
                # send/receive shape varies by node; accept type send only when
                # this address matches the block's account (it is the receiver's
                # history), which it is by construction of the query.
                if etype == "send" and entry.get("account") == account.address:
                    return entry.get("hash")
        return None

    def verify_payment(
        self,
        request_id: str,
        amount_raw: int,
        require_onchain: bool = True,
    ) -> dict:
        """Verify that `amount_raw` was paid to the one-time address for
        request_id. Returns:

          {"status": "approved", "request_id", "address", "tx_hash"}
              on the FIRST sighting of the matching on-chain send.
          {"status": "spent", ...}
              if this request_id was already approved (replay refused).
          {"status": "pending", ...}
              if no matching on-chain send is seen yet.
        """
        acct = self.one_time_account(request_id)
        # exactly-once: previous approval wins, always.
        existing = self.store.get(request_id)
        if existing and existing["status"] == "approved":
            return {
                "status": "spent",
                "request_id": request_id,
                "address": acct.address,
                "tx_hash": existing["tx_hash"],
            }

        if require_onchain:
            tx_hash = self._onchain_paid(acct, amount_raw)
            if tx_hash is None:
                return {
                    "status": "pending",
                    "request_id": request_id,
                    "address": acct.address,
                }
        else:
            tx_hash = "simulated"

        # claim exactly-once (atomic sqlite insert)
        claimed = self.store.claim(request_id, tx_hash, acct.address, amount_raw)
        if not claimed:
            # raced with a concurrent approval -> replay refused
            existing = self.store.get(request_id)
            return {
                "status": "spent",
                "request_id": request_id,
                "address": acct.address,
                "tx_hash": existing["tx_hash"] if existing else tx_hash,
            }
        return {
            "status": "approved",
            "request_id": request_id,
            "address": acct.address,
            "tx_hash": tx_hash,
        }
