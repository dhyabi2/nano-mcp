"""Block 15 tests: the MCP `paidTool` wrapper for the x402 exact-on-nano scheme.

Roadmap stage 1 requires an MCP `paidTool` wrapper in addition to the spec +
reference implementation (blocks 10-11), the self-hostable facilitator (12-13)
and the HTTP Resource Server + wire client (14). This is that wrapper: two MCP
tools reusing the SAME ResourceApp + Facilitator the HTTP server uses, so an MCP
client agent can request a paid tool (one-time payTo + exact amount), send XNO,
then get the protected result exactly once.

  L22 — the paidTool wrapper issues a one-time nano payTo then serves the result
        only after the proof is verified and settled on two independent RPCs.
  L21 — a spent/replayed proof is refused, so one payment never serves the
        protected tool a second time.

No funds move and no live node is touched: the RPC endpoints are stub
`RpcEndpoint`s backed by an in-memory block store emitting the REAL Nano
block_info shape (block_account / contents.type / contents.destination /
confirmed as the STRING "true") that block 13 taught the verifier to parse.
"""
import asyncio
import json

import pytest

from nano_mcp.facilitator import Facilitator, FacilitatorConfig, RpcEndpoint
from nano_mcp.paidtool import PaidToolServer, build_paid_server

AMOUNT_RAW = "1000000000000000000000000000000"  # 1 XNO raw
PAYER = "nano_3p1zmep1qax1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f9"


class BlockStore:
    """In-memory block_info store emitting the REAL Nano node shape."""

    def __init__(self):
        self.blocks: dict[str, dict] = {}

    def add(self, block_hash: str, *, pay_to: str, amount: str = AMOUNT_RAW,
            confirmed: bool = True):
        self.blocks[block_hash] = {
            "block_account": PAYER,
            "amount": str(amount),
            "confirmed": "true" if confirmed else "false",
            "contents": {"type": "send", "destination": pay_to},
        }

    def call(self, action: str, params: dict) -> dict:
        block = self.blocks.get(params.get("hash", ""))
        if block is None:
            raise RuntimeError(f"unknown block {params.get('hash')}")
        return block


def make_endpoint(store: BlockStore, url: str = "https://rpc.nano.to") -> RpcEndpoint:
    return RpcEndpoint(url=url, call=store.call)


def _proof_for(idx: int) -> str:
    return f"{idx:040x}{'D' * 24}"  # 40 + 24 = 64 hex


class WalletPayer:
    """The client's wallet: 'broadcasts' a confirmed send into both nodes."""

    def __init__(self, stores: list[BlockStore]):
        self.stores = stores
        self.sent: list[tuple[str, str, str]] = []

    def pay(self, pay_to: str, amount_raw: str) -> str:
        proof = _proof_for(len(self.sent) + 1)
        for store in self.stores:
            store.add(proof, pay_to=pay_to, amount=amount_raw)
        self.sent.append((pay_to, amount_raw, proof))
        return proof


def _build_stub(broken: bool = False):
    store_a, store_b = BlockStore(), BlockStore()
    endpoints = [make_endpoint(store_a), make_endpoint(store_b, "https://secondary.nano.city")]
    if broken:
        endpoints[1] = RpcEndpoint(
            url="https://broken.example",
            call=lambda a, p: (_ for _ in ()).throw(RuntimeError("down")),
        )
    facilitator = Facilitator(FacilitatorConfig(endpoints=endpoints))

    def handler(resource: dict) -> dict:
        return {"ok": True, "data": "the protected tool result", "resource": resource["description"]}

    paid = PaidToolServer(
        master_secret=bytes(range(32)),
        facilitator=facilitator,
        amount_raw=AMOUNT_RAW,
        tools={"premium_data": handler},
    )
    return paid, store_a, store_b


async def _server(*, broken: bool = False):
    """Build the MCPServer in the CURRENT loop and register its tools."""
    paid, _a, _b = _build_stub(broken=broken)
    server = build_paid_server(paid)
    await server.list_tools()
    return server, paid, _a, _b


async def _text(res) -> str:
    return "".join(c.text for c in res.content)


async def _as_dict(res) -> dict:
    return json.loads(await _text(res))


def test_paidtool_tools_exposed():
    async def main():
        server, _paid, _a, _b = await _server()
        names = {t.name for t in await server.list_tools()}
        assert {"paid_tool_request", "paid_tool_execute"} <= names
    asyncio.run(main())


def test_request_issues_one_time_payto():
    async def main():
        server, _paid, _a, _b = await _server()
        r1 = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        r2 = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        assert r1["request_id"] != r2["request_id"]
        assert r1["pay_to"] != r2["pay_to"]
        assert r1["pay_to"].startswith("nano_")
        assert r1["scheme"] == "exact"
        assert r1["network"] == "nano:live"
        assert r1["asset"] == "XNO"
        assert r1["amount_raw"] == AMOUNT_RAW
    asyncio.run(main())


def test_request_is_stateless_and_deterministic():
    """The wrapper stores no per-request state: the one-time payTo is derived
    deterministically from (master, request_id), so re-deriving the requirement
    for an already-issued request_id yields the SAME payTo and amount with no
    resource-side bookkeeping (mirrors the stateless HTTP 402 server)."""
    async def main():
        server, _paid, _a, _b = await _server()
        r = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        # Every fresh request() must issue a distinct one-time payTo.
        r2 = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        assert r2["request_id"] != r["request_id"]
        assert r2["pay_to"] != r["pay_to"]
        # Determinism: the same request_id re-derived yields the same one-time payTo.
        from nano_mcp.httpx402 import derive_requirements
        req = derive_requirements(bytes(range(32)), r["request_id"], AMOUNT_RAW)
        assert req["payTo"] == r["pay_to"]
        assert req["amount"] == AMOUNT_RAW
    asyncio.run(main())


@pytest.fixture
def paid_and_payer():
    paid, store_a, store_b = _build_stub()
    payer = WalletPayer([store_a, store_b])
    return paid, payer


def test_execute_serves_result_after_verify_and_settle(paid_and_payer):
    """L22: request -> pay -> execute verifies on two RPCs, settles exactly once
    and serves the protected tool result."""
    async def main():
        paid, payer = paid_and_payer
        # Call the MCP server as an agent would.
        server = build_paid_server(paid)
        await server.list_tools()
        req = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        proof = payer.pay(req["pay_to"], req["amount_raw"])
        out = await _as_dict(await server.call_tool(
            "paid_tool_execute",
            {"tool": "premium_data", "request_id": req["request_id"], "payment_proof": proof},
        ))
        assert out["success"] is True
        assert out["ok"] is True
        assert out["result"]["data"] == "the protected tool result"
        assert out["settlement"]["success"] is True
        assert out["settlement"]["transaction"] == proof
        assert out["settlement"]["network"] == "nano:live"
    asyncio.run(main())


def test_replay_is_refused_once(paid_and_payer):
    """L21: re-executing the same proof + request_id is refused and never serves
    the protected tool a second time."""
    async def main():
        paid, payer = paid_and_payer
        server = build_paid_server(paid)
        await server.list_tools()
        req = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        proof = payer.pay(req["pay_to"], req["amount_raw"])
        first = await _as_dict(await server.call_tool(
            "paid_tool_execute",
            {"tool": "premium_data", "request_id": req["request_id"], "payment_proof": proof},
        ))
        assert first["success"] is True
        second = await _as_dict(await server.call_tool(
            "paid_tool_execute",
            {"tool": "premium_data", "request_id": req["request_id"], "payment_proof": proof},
        ))
        assert second["success"] is False
        assert "result" not in second
    asyncio.run(main())


def test_fail_closed_single_endpoint_refuses():
    """One of two independent endpoints erroring refuses the whole payment."""
    async def main():
        server, _paid, store_a, _store_b = await _server(broken=True)
        payer = WalletPayer([store_a])
        req = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        proof = payer.pay(req["pay_to"], req["amount_raw"])
        out = await _as_dict(await server.call_tool(
            "paid_tool_execute",
            {"tool": "premium_data", "request_id": req["request_id"], "payment_proof": proof},
        ))
        assert out["success"] is False
        assert "result" not in out
    asyncio.run(main())


def test_wrong_amount_is_refused():
    """A payment proof whose amount differs from the issued requirement is
    refused: the wrapper re-derives the exact amount it issued."""
    async def main():
        server, _paid, store_a, store_b = await _server()
        payer = WalletPayer([store_a, store_b])
        req = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        wrong = "2" + req["amount_raw"][1:]  # tamper the exact amount
        proof = payer.pay(req["pay_to"], wrong)
        out = await _as_dict(await server.call_tool(
            "paid_tool_execute",
            {"tool": "premium_data", "request_id": req["request_id"], "payment_proof": proof},
        ))
        assert out["success"] is False
        assert "result" not in out
    asyncio.run(main())


def test_missing_request_id_is_refused():
    """An execute with no request_id cannot re-derive the one-time payTo and is
    refused (structural request binding, no memo)."""
    async def main():
        server, _paid, store_a, store_b = await _server()
        payer = WalletPayer([store_a, store_b])
        req = await _as_dict(await server.call_tool("paid_tool_request", {"tool": "premium_data"}))
        proof = payer.pay(req["pay_to"], req["amount_raw"])
        out = await _as_dict(await server.call_tool(
            "paid_tool_execute",
            {"tool": "premium_data", "request_id": "", "payment_proof": proof},
        ))
        assert out["success"] is False
        assert "result" not in out
    asyncio.run(main())
