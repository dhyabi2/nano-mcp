"""Block 4: the MCP server drives the pay-per-call tools in-process (mcp v2).

Verifies L4 (quote returns a distinct one-time address per request_id, stable on
repeat) and L5 (verify_payment approves exactly once) through the real MCPServer
tool surface, not just the service class.
"""
import asyncio
import json

import pytest

from nano_mcp.server import build_server
from nano_mcp.service import PaymentService
from nano_mcp.store import ApprovalStore
from nano_sdk.units import nano_to_raw

MASTER = bytes.fromhex("22" * 32)


class StubClient:
    def __init__(self):
        self.incoming: dict[str, list] = {}
        self.accounts_balance: dict[str, str] = {}

    def account_history(self, account: str, count: int = 20):
        return {
            "account": account,
            "history": [
                {"type": "receive", "account": account, "amount": str(amt), "hash": txh}
                for amt, txh in self.incoming.get(account, [])
            ],
        }

    def account_balance(self, account: str) -> dict:
        return {"balance": self.accounts_balance.get(account, "0")}


async def _text(res) -> str:
    return "".join(c.text for c in res.content)


async def _as_dict(res) -> dict:
    return json.loads(await _text(res))


async def _make_server(tmp_path):
    stub = StubClient()
    pay = PaymentService(MASTER, stub, ApprovalStore(path=str(tmp_path / "m.db")))
    return build_server(pay), stub


def test_mcp_quote_distinct_and_stable(tmp_path):
    async def main():
        server, _ = await _make_server(tmp_path)
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert {"quote", "verify_payment", "get_address", "get_balance", "get_history"} <= names

        q1 = await _as_dict(await server.call_tool("quote", {"price_nano": "0.001"}))
        q2 = await _as_dict(await server.call_tool("quote", {"price_nano": "0.001"}))
        assert q1["request_id"] != q2["request_id"]
        assert q1["address"] != q2["address"]
        assert q1["price_raw"] == q2["price_raw"]

        qs1 = await _as_dict(await server.call_tool(
            "quote", {"price_nano": "0.001", "request_id": "fixed"}
        ))
        qs2 = await _as_dict(await server.call_tool(
            "quote", {"price_nano": "0.001", "request_id": "fixed"}
        ))
        assert qs1["address"] == qs2["address"]

    asyncio.run(main())


def test_mcp_verify_approves_once(tmp_path):
    async def main():
        server, stub = await _make_server(tmp_path)
        rid = "mcp-l5"
        amt = int(nano_to_raw("0.005"))
        addr = PaymentService(MASTER, stub, ApprovalStore(path=str(tmp_path / "x.db"))).one_time_account(rid).address
        stub.incoming[addr] = [(amt, "E" * 64)]

        v1 = await _as_dict(await server.call_tool(
            "verify_payment", {"request_id": rid, "amount_raw": str(amt)}
        ))
        v2 = await _as_dict(await server.call_tool(
            "verify_payment", {"request_id": rid, "amount_raw": str(amt)}
        ))
        assert v1["status"] == "approved"
        assert v2["status"] == "spent"

    asyncio.run(main())
