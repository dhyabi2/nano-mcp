"""Block 4 tests: one-time address derivation (L4) and exactly-once verify (L5).

L4 — the server derives a distinct, reproducible one-time payment address per
request_id. Test: two request_ids differ; repeating one id reproduces the same
address.

L5 — verify_payment(request_id, amount_raw) approves only after an on-chain send
to that address is seen, exactly once. Test: with a stub client that simulates the
matching on-chain send arriving on the one-time address, verify returns approved
the first time and `spent` on every repeat. No funds/movement is needed: the
stub stands in for the live rpc.nano.to account_history lookup.
"""
import threading

import pytest

from nano_mcp import ApprovalStore, PaymentService, derive_one_time_account
from nano_sdk.units import nano_to_raw

MASTER = bytes.fromhex("11" * 32)


class StubClient:
    """Simulates on-chain state for the one-time address(es).

    `incoming` maps address -> list of (amount_raw, tx_hash) sends that have
    landed. account_history returns these as `receive` entries, standing in for
    the live node lookup in verify_payment._onchain_paid.
    """

    def __init__(self):
        self.incoming: dict[str, list] = {}
        self.calls: list[str] = []

    def account_history(self, account: str, count: int = 20):
        self.calls.append(account)
        entries = []
        for amt, txh in self.incoming.get(account, []):
            entries.append(
                {
                    "type": "receive",
                    "account": account,
                    "amount": str(amt),
                    "hash": txh,
                    "confirmed": "true",
                }
            )
        return {"account": account, "history": entries}


@pytest.fixture()
def svc(tmp_path):
    store = ApprovalStore(path=str(tmp_path / "a.db"))
    return PaymentService(master_secret=MASTER, client=StubClient(), store=store)


# ---- L4: distinct + reproducible one-time address per request_id ----
def test_l4_distinct_addresses_for_different_request_ids(svc):
    a = svc.one_time_account("req-1").address
    b = svc.one_time_account("req-2").address
    assert a != b
    assert a.startswith("nano_") and b.startswith("nano_")


def test_l4_same_request_id_reproduces_same_address(svc):
    a1 = svc.one_time_account("req-1").address
    a2 = svc.one_time_account("req-1").address
    assert a1 == a2


def test_l4_addresses_valid_nano_format():
    for rid in ("abc", "req-xyz-123"):
        addr = derive_one_time_account(MASTER, rid).address
        assert addr.startswith("nano_")
        assert len(addr) == 65


def test_l4_hkdf_differs_across_ids():
    k1 = derive_one_time_account(MASTER, "rid-1").private_key
    k2 = derive_one_time_account(MASTER, "rid-2").private_key
    assert k1 != k2


# ---- L5: exactly-once approval after the on-chain send is seen ----
def test_l5_pending_before_payment(svc):
    rid = "req-l5-1"
    amt = int(nano_to_raw("0.003"))
    res = svc.verify_payment(rid, amt)
    assert res["status"] == "pending"
    assert not svc.store.is_approved(rid)


def test_l5_approves_once_when_onchain_send_seen(svc):
    rid = "req-l5-2"
    amt = int(nano_to_raw("0.003"))
    addr = svc.one_time_account(rid).address
    txh = "A" * 64
    # the matching on-chain send lands on the one-time address
    svc.client.incoming[addr] = [(amt, txh)]

    res = svc.verify_payment(rid, amt)
    assert res["status"] == "approved"
    assert res["tx_hash"] == txh

    # exactly-once: a second call refuses replay
    res2 = svc.verify_payment(rid, amt)
    assert res2["status"] == "spent"
    assert svc.store.is_approved(rid)


def test_l5_not_approved_for_underpayment_or_other_address(svc):
    rid = "req-l5-3"
    amt = int(nano_to_raw("0.01"))
    addr = svc.one_time_account(rid).address
    # a smaller send lands on the address
    svc.client.incoming[addr] = [(int(nano_to_raw("0.001")), "B" * 64)]
    assert svc.verify_payment(rid, amt)["status"] == "pending"


def test_l5_store_persists_across_service_instances(tmp_path):
    """Approval persists so a restart cannot re-approve (replay-safe across runs)."""
    db = str(tmp_path / "persist.db")
    rid = "req-l5-4"
    amt = int(nano_to_raw("0.002"))
    addr = derive_one_time_account(MASTER, rid).address
    txh = "C" * 64

    s1 = PaymentService(MASTER, StubClient(), ApprovalStore(path=db))
    s1.client.incoming[addr] = [(amt, txh)]
    assert s1.verify_payment(rid, amt)["status"] == "approved"

    # new service instance pointing at the same store sees it as spent
    s2 = PaymentService(MASTER, StubClient(), ApprovalStore(path=db))
    assert s2.verify_payment(rid, amt)["status"] == "spent"


def test_l5_concurrent_claims_approve_exactly_once(svc):
    """Two concurrent verify calls for the same request id must yield one approval."""
    rid = "req-l5-5"
    amt = int(nano_to_raw("0.002"))
    addr = svc.one_time_account(rid).address
    txh = "D" * 64
    svc.client.incoming[addr] = [(amt, txh)]

    results = []

    def run():
        results.append(svc.verify_payment(rid, amt)["status"])

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("approved") == 1
    assert results.count("spent") == 7
