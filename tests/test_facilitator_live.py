"""Block 13 tests: the multi-RPC verifier parses the REAL Nano block_info shape.

Block 12 left one honest gap: `verify_block_on_independent_endpoints` parsed only
the stub response shape (account / link_as_account / subtype / confirmed:bool),
so against real Nano RPC nodes (which return block_account / contents.type /
contents.destination / confirmed:"true" STRING) it emitted an EMPTY payer and
relied on fallbacks. Block 13 normalizes every node's response via
`normalize_block_info` and proves a real on-chain send block confirms on two
*independent public* RPC endpoints with a non-empty payer.

L18 — the multi-RPC verifier parses the real Nano block_info shape and confirms a
      real on-chain send on two independent public endpoints.
"""
import httpx
import pytest

from nano_mcp.facilitator import (
    RpcError,
    RpcEndpoint,
    normalize_block_info,
    verify_block_on_independent_endpoints,
)

REAL_BLOCK = "ECCB8CB65CD3106EDA8CE9AA893FEAD497A91BCA903890CBD7A5C59F06AB9113"
REAL_PAYTO = "nano_1111111111111111111111111111111111111111111111111111hifc8npp"
REAL_AMOUNT = "205676479000000000000000000000000000000"
REAL_PAYER = "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3"


# ---------------------------------------------------------------- offline shape


def test_normalize_parses_real_nano_block_info_shape():
    """The exact shape real nodes return: block_account, contents.type,
    contents.destination, confirmed as a STRING "true"."""
    raw = {
        "block_account": REAL_PAYER,
        "amount": REAL_AMOUNT,
        "confirmed": "true",
        "contents": {
            "type": "send",
            "destination": REAL_PAYTO,
        },
    }
    nb = normalize_block_info(raw)
    assert nb.account == REAL_PAYER
    assert nb.subtype == "send"
    assert nb.destination == REAL_PAYTO
    assert nb.amount_raw == int(REAL_AMOUNT)
    assert nb.confirmed is True
    assert nb.is_send is True


def test_normalize_accepts_stub_shape_and_bool_confirmed():
    """The old stub shape (account/link_as_account/subtype/bool) still works."""
    nb = normalize_block_info(
        {
            "account": REAL_PAYER,
            "amount": REAL_AMOUNT,
            "confirmed": True,
            "subtype": "send",
            "link_as_account": REAL_PAYTO,
        }
    )
    assert nb.account == REAL_PAYER
    assert nb.subtype == "send"
    assert nb.destination == REAL_PAYTO
    assert nb.confirmed is True


def test_normalize_rejects_missing_confirmed():
    with pytest.raises(RpcError):
        normalize_block_info({"amount": REAL_AMOUNT})


def test_normalize_rejects_missing_amount():
    with pytest.raises(RpcError):
        normalize_block_info({"confirmed": "true"})
    with pytest.raises(RpcError):
        normalize_block_info({"confirmed": "true", "amount": None})


def test_normalize_marks_unconfirmed_from_string():
    nb = normalize_block_info({"confirmed": "false", "amount": REAL_AMOUNT})
    assert nb.confirmed is False


# ------------------------------------------------------------- fail-closed node


def test_incomplete_node_response_is_refused_not_passed():
    """A node that returns a malformed/incomplete block_info must REFUSE the
    whole verification (fail closed), never count as 'confirmed but missing'."""

    def good(action, params):
        return {
            "block_account": REAL_PAYER,
            "amount": REAL_AMOUNT,
            "confirmed": "true",
            "contents": {"type": "send", "destination": REAL_PAYTO},
        }

    def incomplete(action, params):
        # returns the block but OMITS the confirmed flag
        return {"amount": REAL_AMOUNT}

    eps = [
        RpcEndpoint(url="https://rpc.nano.to", call=good),
        RpcEndpoint(url="https://broken.example", call=incomplete),
    ]
    res = verify_block_on_independent_endpoints(eps, REAL_BLOCK, REAL_PAYTO, REAL_AMOUNT)
    assert res.ok is False
    assert res.consulted == 2
    assert "missing 'confirmed'" in (res.reason or "")


def test_wrong_destination_refused_from_real_shape():
    def call(action, params):
        return {
            "block_account": REAL_PAYER,
            "amount": REAL_AMOUNT,
            "confirmed": "true",
            "contents": {"type": "send", "destination": "nano_1notthepayto123"},
        }

    eps = [RpcEndpoint(url="https://a", call=call), RpcEndpoint(url="https://b", call=call)]
    res = verify_block_on_independent_endpoints(eps, REAL_BLOCK, REAL_PAYTO, REAL_AMOUNT)
    assert res.ok is False
    assert "pays" in (res.reason or "")


# ------------------------------------------------------------- live two-RPC test


def test_live_confirms_real_send_on_two_independent_public_rpcs():
    """L18: a real, confirmed, on-chain Nano send block is approved on TWO
    independent public RPC endpoints with a non-empty payer and confirmed_on==2.

    Uses rpc.nano.to and rainstorm.city/api (both proven reachable and serving
    block_info with the real shape). This is READ-ONLY: no funds move, no
    blocks are created. Skipped if either endpoint is unreachable so the suite
    never flakes on transient network outages.
    """
    eps = []
    for url in ("https://rpc.nano.to", "https://rainstorm.city/api"):
        eps.append(RpcEndpoint(url=url, timeout=20))

    # reachability guard: both must serve block_info for the real block
    for ep in eps:
        try:
            ep.invoke("block_info", hash=REAL_BLOCK)
        except Exception:  # noqa: BLE001 - transient network => skip, don't fail
            pytest.skip(f"endpoint {ep.url} unreachable for live test")

    res = verify_block_on_independent_endpoints(eps, REAL_BLOCK, REAL_PAYTO, REAL_AMOUNT)
    assert res.ok is True, f"live 2-RPC verification failed: {res.reason}"
    assert res.confirmed_on == 2
    assert res.consulted == 2
    send = res.confirmed_sends[0]
    # THE bug block 13 fixes: the payer must NOT be empty against real nodes.
    assert send["payer"] == REAL_PAYER
    assert send["receiver"] == REAL_PAYTO
    assert send["amount"] == REAL_AMOUNT