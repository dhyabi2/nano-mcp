"""Block 7 tests: Buyer SDK — owner-signed Ed25519 mandates (L10) and
per-session / daily / balance cap enforcement (L11).

L10 — a buyer session spends only under a valid owner-signed, unexpired
mandate bound to its own sub-account. Tests: a valid mandate authorizes a send;
a tampered signature, a wrong owner public key, an expired mandate, or a
mandate bound to a different sub-account all raise before the client records
any process call.

L11 — the SDK enforces a per-session cap, the daily cap, and the balance guard
before broadcast. Tests: sending over the session cap, over the daily 0.01 XNO
cap, or over the on-chain balance raises with no client process call recorded;
sending up to the session cap is allowed and recorded.

Uses a stub client (no network, no funds), consistent with the existing
wallet-guard tests.
"""
import time

import pytest

from nano_sdk.buyer import (
    DailyCapExceeded,
    ExpiredMandate,
    Mandate,
    MandateError,
    SessionCapExceeded,
    SessionWallet,
    derive_session_account,
    issue_mandate,
    verify_mandate,
)
from nano_sdk.crypto import derive_account
from nano_sdk.units import nano_to_raw
from nano_sdk.wallet import DEFAULT_DAILY_CAP_RAW, InsufficientBalance

MASTER = bytes.fromhex("22" * 32)          # owner master seed (derives session subs)
OWNER_ACCT = derive_account(MASTER, 0)      # owner's own account (signing key)
OWNER_PUB = OWNER_ACCT.public_key
OWNER_PRIV = OWNER_ACCT.private_key

REP = "nano_1stofnrxuz3cai7ze75o174bpm7scwj9jn3nxsn8ntzg784jf1gzn1jjdkou"
DEST = "nano_1q3hqecaw15cjt7thbtxu3pbzr1eihtzzpzxguoc37bj1wc5ffoh7w74gi6p"

CAP_RAW = int(nano_to_raw("0.003"))        # per-session cap


class StubClient:
    def __init__(self, balance_raw: int = int(nano_to_raw("0.005"))):
        self.balance_raw = balance_raw
        self.frontier = "AB" * 32
        self.calls: list[dict] = []
        self.process_result = {"hash": "CD" * 32}

    def account_info(self, account: str) -> dict:
        return {
            "balance": str(self.balance_raw),
            "frontier": self.frontier,
            "representative": REP,
        }

    def call(self, **payload) -> dict:
        self.calls.append(payload)
        if payload["action"] == "process":
            return self.process_result
        if payload["action"] == "work_generate":
            return {"work": "0000000000000000"}
        raise AssertionError(f"unexpected action {payload}")

    def process_calls(self) -> list[dict]:
        return [c for c in self.calls if c["action"] == "process"]


def make_session(session_id="sess-1", cap_raw=CAP_RAW, expires_in=3600, client=None, now=None):
    """Build a valid session: derive its sub-account, sign a mandate, wrap."""
    now = now if now is not None else time.time()
    acct = derive_session_account(MASTER, session_id)
    mandate = issue_mandate(
        OWNER_PRIV, session_id, acct.address, cap_raw,
        expires_at=now + expires_in, issued_at=now,
    )
    wallet = SessionWallet(
        acct, OWNER_PUB, mandate,
        client=client or StubClient(), clock=lambda: now,
    )
    return wallet, acct, mandate


# ======================= L10: valid mandate authorizes =====================
def test_l10_valid_mandate_authorizes_send():
    wallet, acct, _ = make_session()
    amount = int(nano_to_raw("0.001"))
    assert verify_mandate(wallet.mandate, OWNER_PUB, now=time.time()) is None
    h, blk = wallet.send(DEST, amount)
    assert h == wallet.client.process_result["hash"]
    assert len(wallet.client.process_calls()) == 1
    assert wallet.available_session() == CAP_RAW - amount


# =================== L10: invalid / misbound / expired refused ===============
def test_l10_tampered_signature_refused_before_broadcast():
    wallet, _, _ = make_session()
    tampered = wallet.mandate.with_signature(b"\x00" * 64)
    client = wallet.client
    with pytest.raises(MandateError):
        SessionWallet(wallet.account, OWNER_PUB, tampered, client=client, clock=wallet.clock)
    assert client.process_calls() == []


def test_l10_wrong_owner_public_key_refused():
    wallet, _, _ = make_session()
    other = derive_account(bytes.fromhex("99" * 32), 0).public_key
    with pytest.raises(MandateError):
        SessionWallet(wallet.account, other, wallet.mandate, client=wallet.client)


def test_l10_expired_mandate_refused():
    now = time.time()
    acct = derive_session_account(MASTER, "sess-expired")
    mandate = issue_mandate(OWNER_PRIV, "sess-expired", acct.address, CAP_RAW,
                            expires_at=now - 5, issued_at=now - 10)
    client = StubClient()
    with pytest.raises(ExpiredMandate):
        SessionWallet(acct, OWNER_PUB, mandate, client=client, clock=lambda: now)
    assert client.process_calls() == []


def test_l10_misbound_mandate_refused():
    """A mandate for sess-A cannot spend sess-B's sub-account."""
    acct = derive_session_account(MASTER, "sess-A")
    other = derive_session_account(MASTER, "sess-B")
    mandate = issue_mandate(OWNER_PRIV, "sess-A", acct.address, CAP_RAW,
                            expires_at=time.time() + 3600)
    with pytest.raises(MandateError):
        SessionWallet(other, OWNER_PUB, mandate, client=StubClient())


# ======================= L11: caps enforced pre-broadcast ===================
def test_l11_over_session_cap_refused():
    client = StubClient(balance_raw=int(nano_to_raw("0.05")))
    wallet, _, _ = make_session(client=client)  # cap = 0.003
    over = CAP_RAW + 1
    with pytest.raises(SessionCapExceeded):
        wallet.send(DEST, over)
    assert client.process_calls() == []


def test_l11_over_daily_cap_refused():
    client = StubClient(balance_raw=int(nano_to_raw("0.05")))
    wallet, _, _ = make_session(client=client,
                                cap_raw=int(nano_to_raw("1.0")))  # room, but daily 0.01
    daily = DEFAULT_DAILY_CAP_RAW  # 0.01 XNO
    with pytest.raises(DailyCapExceeded):
        wallet.send(DEST, daily + int(nano_to_raw("0.000001")))
    assert client.process_calls() == []


def test_l11_over_balance_refused():
    client = StubClient(balance_raw=int(nano_to_raw("0.001")))
    wallet, _, _ = make_session(client=client)
    with pytest.raises(Exception) as ei:
        wallet.send(DEST, int(nano_to_raw("0.002")))
    # either balance guard or session cap catches it, but never a broadcast
    assert isinstance(ei.value, (InsufficientBalance, SessionCapExceeded))
    assert client.process_calls() == []


def test_l11_up_to_session_cap_allowed_and_recorded():
    client = StubClient(balance_raw=int(nano_to_raw("0.05")))
    wallet, _, _ = make_session(client=client)
    wallet.send(DEST, CAP_RAW)  # exactly the cap
    assert wallet.available_session() == 0
    assert len(client.process_calls()) == 1
    # a second spend is now over the session cap
    with pytest.raises(SessionCapExceeded):
        wallet.send(DEST, 1)
    assert len(client.process_calls()) == 1


# ======================= session isolation (must hold too) ==================
def test_sessions_derive_distinct_subaccounts():
    a = derive_session_account(MASTER, "sess-1").address
    b = derive_session_account(MASTER, "sess-2").address
    assert a != b
    assert a.startswith("nano_") and b.startswith("nano_")
    # deterministic: repeating a session reproduces the account
    assert derive_session_account(MASTER, "sess-1").private_key == derive_session_account(MASTER, "sess-1").private_key