"""A send must not re-delegate the account it pays from.

Both send paths carry the account's existing representative into the block they
sign:

    nano_sdk/wallet.py   rep = info.get("representative") or self.representative
    nano_sdk/buyer.py    rep = info.get("representative") or self.account.address

A fallback is right for an unopened account, which has no representative yet.
But `account_info` was called without `representative="true"`, and a Nano node
-- rpc.nano.to included -- does not send that key unless asked. So the read
NEVER found a representative and the fallback was taken on every send: a
`Wallet` re-pointed the account at `DEFAULT_REPRESENTATIVE` (NanoFusion), and a
`SessionBuyer` re-pointed the sub-account at itself. Signed, published, and
invisible: the representative is a hash-covered field of the block, so this is a
real change to the ledger every single time money moves.

Nothing noticed because every stub in the suite answers `account_info` with a
`representative` key the real node never sends. `FaithfulNode` below answers the
way the node actually does -- the field appears only when the request asks for
it -- so these tests fail unless the request asks.
"""
import os

import httpx
import pytest

from nano_sdk import Wallet, nano_to_raw
from nano_sdk.client import RpcClient

SEED = "00" * 32
DEST = "nano_1q3hqecaw15cjt7thbtxu3pbzr1eihtzzpzxguoc37bj1wc5ffoh7w74gi6p"
# The representative the account actually has on chain: not NanoFusion, and not
# the account's own address, so whichever fallback is taken is visible.
CHOSEN_REP = "nano_3patrick68y5btibaujyu7zokw7ctu4onikarddphra6qt688xzrszcg4yuo"
FRONTIER = "AB" * 32


class FaithfulNode:
    """`httpx.post` replacement that answers like rpc.nano.to.

    Checked against the live node on 2026-10-12: `account_info` returns
    `account_version, balance, balance_nano, block_count, confirmation_height,
    confirmation_height_frontier, frontier, modified_timestamp, open_block,
    representative_block` -- and `representative` ONLY when the request carries
    `representative: "true"`.
    """

    def __init__(self, balance_raw: int, rep: str | None = None):
        self.balance_raw = balance_raw
        self.rep = rep
        self.payloads: list[dict] = []

    def __call__(self, url, **kwargs):
        payload = kwargs["json"]
        self.payloads.append(payload)
        action = payload.get("action")
        if action == "account_info":
            body = {
                "frontier": FRONTIER,
                "open_block": FRONTIER,
                "representative_block": FRONTIER,
                "balance": str(self.balance_raw),
                "modified_timestamp": "1700000000",
                "block_count": "3",
                "account_version": "2",
                "confirmation_height": "3",
                "confirmation_height_frontier": FRONTIER,
            }
            if self.rep is not None and str(payload.get("representative", "")).lower() == "true":
                body["representative"] = self.rep
            return httpx.Response(200, json=body)
        if action == "work_generate":
            return httpx.Response(200, json={"work": "0000000000000000"})
        if action == "process":
            return httpx.Response(200, json={"hash": "CD" * 32})
        raise AssertionError(f"unexpected action {payload}")

    def sent(self, action: str) -> dict:
        return [p for p in self.payloads if p.get("action") == action][0]


@pytest.fixture
def node(monkeypatch):
    def _node(balance_raw: int, rep: str | None = CHOSEN_REP) -> FaithfulNode:
        """`rep=None` answers with no representative key at all (an unopened
        account); `rep=""` answers with a blank one."""
        n = FaithfulNode(balance_raw, rep)
        monkeypatch.setattr(httpx, "post", n)
        return n
    return _node


def test_account_info_asks_the_node_for_the_representative(node):
    n = node(int(nano_to_raw("0.005")))
    RpcClient(url="https://rpc.invalid").account_info(DEST)
    assert str(n.sent("account_info").get("representative", "")).lower() == "true", (
        "without representative=true the node sends no representative, so every "
        "caller that reads one finds nothing"
    )


def test_account_info_actually_returns_a_representative(node):
    node(int(nano_to_raw("0.005")))
    info = RpcClient(url="https://rpc.invalid").account_info(DEST)
    assert info.get("representative") == CHOSEN_REP


def test_a_send_keeps_the_accounts_own_representative(node):
    """The whole point: the published block must not re-delegate the account."""
    n = node(int(nano_to_raw("0.005")))
    w = Wallet(seed=SEED, client=RpcClient(url="https://rpc.invalid"))
    _, blk = w.send(DEST, int(nano_to_raw("0.001")))
    assert blk["representative"] == CHOSEN_REP, (
        f"the send re-delegated the account to {blk['representative']}"
    )
    assert n.sent("process")["block"]["representative"] == CHOSEN_REP


@pytest.mark.parametrize("rep,label", [(None, "no representative key"), ("", "a blank one")])
def test_an_answer_with_no_usable_representative_still_falls_back(node, rep, label):
    """The case the fallback is for, and the reason it is `or` and not a default.

    An unopened account has no representative, and `get(k, d)` would have handed
    a blank string straight to `public_key_from_address`. Both answers must take
    the wallet's own default instead, and the block must still be signable.
    """
    node(int(nano_to_raw("0.005")), rep=rep)
    w = Wallet(seed=SEED, client=RpcClient(url="https://rpc.invalid"))
    _, blk = w.send(DEST, int(nano_to_raw("0.001")))
    assert blk["representative"] == w.representative, label
    assert len(blk["signature"]) == 128


def test_a_session_send_keeps_the_sub_accounts_representative(node):
    """The buyer SDK has the same read, with a worse fallback.

    `nano_sdk/buyer.py`'s default was the sub-account's OWN address, so every
    session payment re-delegated the sub-account to itself -- an account with no
    voting weight behind it.
    """
    import time as _time

    from nano_sdk.buyer import SessionWallet, derive_session_account, issue_mandate
    from nano_sdk.crypto import derive_account

    master = bytes.fromhex("22" * 32)
    owner = derive_account(master, 0)
    now = _time.time()
    acct = derive_session_account(master, "sess-rep")
    mandate = issue_mandate(
        owner.private_key, "sess-rep", acct.address, int(nano_to_raw("0.003")),
        expires_at=now + 3600, issued_at=now,
    )

    node(int(nano_to_raw("0.005")))
    wallet = SessionWallet(
        acct, owner.public_key, mandate,
        client=RpcClient(url="https://rpc.invalid"), clock=lambda: now,
    )
    _, blk = wallet.send(DEST, int(nano_to_raw("0.001")))
    assert blk["representative"] == CHOSEN_REP, (
        f"the session send re-delegated the sub-account to {blk['representative']}"
    )
    assert blk["representative"] != acct.address


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("NANO_RPC_URL"), reason="NANO_RPC_URL not set")
def test_the_live_node_sends_no_representative_unless_asked():
    """The fact the whole fix rests on, read from the node itself."""
    client = RpcClient()
    bare = client.call(action="account_info", account=CHOSEN_REP)
    assert "representative" not in bare, (
        "rpc.nano.to now sends a representative unasked; re-read this fix"
    )
    assert client.account_info(CHOSEN_REP).get("representative")
