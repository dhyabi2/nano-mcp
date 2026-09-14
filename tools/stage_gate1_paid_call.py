"""Block 19, L28: real funded paid mainnet call through nano-mcp (stage gate 1, step 2).

The treasury (now funded with the owner's 10 XNO, receive block C99C1BC1...) acts as
the FIRST BUYER: it requests a nano-mcp paid tool via the MCP paidTool wrapper, is told
a one-time nano_ payTo and an exact raw amount, sends exactly that amount on mainnet
from the treasury wallet, then calls paid_tool_execute with the resulting 64-hex send
block hash. The paid server (ResourceApp + Facilitator) verifies the send on two
independent public RPC endpoints (rpc.nano.to + rainstorm.city/api) fail-closed and
settles it with an atomic single-use claim, serving the protected result exactly once;
a replayed/spent proof is refused.

This is REAL funded on-chain movement that closes the standing L2 gap honestly
(a signed send accepted and confirmed via rpc.nano.to) WITHOUT faking: funding received
is never goal evidence, and no adoption/share is claimed. The amount is the smallest
practical so we spend the least XNO.
"""
from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, "/root/nano-agent/nano-mcp")

from nano_mcp.facilitator import Facilitator, FacilitatorConfig, RpcEndpoint
from nano_mcp.paidtool import PaidToolServer
from nano_sdk import RpcClient, Wallet
from nano_sdk.units import nano_to_raw

SEED = os.environ["NANO_AGENT_SEED"]
ACCOUNT = os.environ["NANO_AGENT_ACCOUNT"]

# The paid tool's price: spend the smallest practical amount (0.0001 XNO).
PRICE_XNO = "0.0001"
AMOUNT_RAW = str(int(nano_to_raw(PRICE_XNO)))

# Server master secret for one-time payTo derivation (a fresh demo key, NOT the seed).
MASTER = base64.b64decode("bmFuby1tY3AtcGFpZC1kZW1vLW1hc3Rlci1zZWNyZXQtMDE=")
assert len(MASTER) >= 16


def protected_tool(resource: dict) -> dict:
    return {"ok": True, "result": "block-19 stage-gate-1 paid result", "resource": resource["description"]}


def main() -> None:
    print("== stage gate 1, step 2: real funded paid mainnet call ==")
    print(f"price: {PRICE_XNO} XNO = {AMOUNT_RAW} raw")
    print(f"buyer (treasury): {ACCOUNT}")

    facilitator = Facilitator(
        FacilitatorConfig(endpoints=[
            RpcEndpoint(url="https://rpc.nano.to"),
            RpcEndpoint(url="https://rainstorm.city/api"),
        ])
    )
    paid = PaidToolServer(
        master_secret=MASTER,
        facilitator=facilitator,
        amount_raw=AMOUNT_RAW,
        tools={"protected_premium": protected_tool},
    )

    # 1. Request a paid tool -> one-time payTo + exact amount.
    req = paid.request("protected_premium")
    print("\nrequest:")
    print(json.dumps(req, indent=2))
    pay_to = req["pay_to"]
    amount_raw = int(req["amount_raw"])
    assert str(amount_raw) == AMOUNT_RAW

    # 2. Send exactly that amount from the treasury wallet (real mainnet).
    client = RpcClient()
    wallet = Wallet(seed=SEED, client=client)
    print(f"\nbalance before send: {wallet.balance_raw() / 10**30} XNO")
    print(f"sending {amount_raw / 10**30} XNO to {pay_to} ...")
    send_hash, blk = wallet.send(pay_to, amount_raw)
    print(f"send block hash: {send_hash}")
    print(f"send block: {json.dumps(blk)}")

    # 3. Execute the paid tool with the send proof -> verify on 2 RPCs + settle once.
    # Nano confirms in ~1s but propagation to BOTH independent endpoints takes a
    # moment; wait for two-RPC consensus (the same fail-closed verifier) before
    # executing, so the paid call is served only against confirmed on-chain proof.
    import time
    from nano_mcp.facilitator import verify_block_on_independent_endpoints
    deadline = time.time() + 90
    vres = verify_block_on_independent_endpoints(
        [RpcEndpoint(url="https://rpc.nano.to"), RpcEndpoint(url="https://rainstorm.city/api")],
        send_hash, pay_to, str(amount_raw),
    )
    while not vres.ok and time.time() < deadline:
        time.sleep(5)
        vres = verify_block_on_independent_endpoints(
            [RpcEndpoint(url="https://rpc.nano.to"), RpcEndpoint(url="https://rainstorm.city/api")],
            send_hash, pay_to, str(amount_raw),
        )
    print(f"\nconfirmation check: ok={vres.ok} reason={vres.reason} consulted={vres.consulted}")
    assert vres.ok, f"send not confirmed on two independent RPCs within 90s: {vres.reason}"

    out = paid.execute("protected_premium", req["request_id"], send_hash)
    print("\nexecute (first):")
    print(json.dumps(out, indent=2))
    assert out.get("success") is True
    assert out.get("result", {}).get("result") == "block-19 stage-gate-1 paid result"

    # 4. Replay/spent proof must be refused (exactly once).
    replay = paid.execute("protected_premium", req["request_id"], send_hash)
    print("\nexecute (replay, must be refused):")
    print(json.dumps(replay, indent=2))
    assert replay.get("success") is False
    assert "result" not in replay

    # 5. Confirm the send appears in treasury account_history on two independent RPCs.
    print("\naccount_history (rpc.nano.to):")
    hist = client.account_history(ACCOUNT, count=3)
    print(json.dumps(hist, indent=2))
    hashes = [h.get("hash") for h in hist.get("history", []) if h.get("type") != "receive"]
    assert send_hash in hashes, f"{send_hash} not in rpc.nano.to history"
    print(f"\nconfirmed on rpc.nano.to: {send_hash}")

    import urllib.request
    body = json.dumps({"action": "account_history", "account": ACCOUNT, "count": 3}).encode()
    uh = urllib.request.Request("https://rainstorm.city/api", data=body,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(uh, timeout=30) as resp:
        rhs = json.loads(resp.read().decode())
    rhs_hashes = [h.get("hash") for h in rhs.get("history", []) if h.get("type") != "receive"]
    assert send_hash in rhs_hashes, f"{send_hash} not in rainstorm history"
    print(f"confirmed on rainstorm.city: {send_hash}")
    print("\nSTAGE GATE 1 PAID CALL DONE — send hash:", send_hash)


if __name__ == "__main__":
    main()
