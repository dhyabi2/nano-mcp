"""Thin JSON-RPC-ish client over the public Nano node at rpc.nano.to.

The node is a full live Nano node exposed over HTTP POST JSON (docs.nano.to/nano-rpc).
Reads (version, account_balance, account_info, account_history, block_info, ...) are free;
write actions (process) and PoW (work_generate) may require the NANO_RPC_KEY.
"""
from __future__ import annotations

import os

import httpx

DEFAULT_RPC_URL = "https://rpc.nano.to"


class RpcError(RuntimeError):
    """Raised when the node returns an error payload or a non-2xx response."""


class RpcClient:
    def __init__(self, url: str | None = None, api_key: str | None = None, timeout: float = 30.0):
        self.url = url or os.environ.get("NANO_RPC_URL") or DEFAULT_RPC_URL
        self.api_key = api_key if api_key is not None else os.environ.get("NANO_RPC_KEY")
        self.timeout = timeout

    def call(self, **payload) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        resp = httpx.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        if resp.status_code != 200:
            raise RpcError(f"rpc.nano.to HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if isinstance(data, dict) and ("error" in data):
            raise RpcError(f"rpc error: {data['error']}")
        return data

    # ---- read actions (free) ----
    def version(self) -> dict:
        return self.call(action="version")

    def account_balance(self, account: str) -> dict:
        """account: nano_ address or @username."""
        return self.call(action="account_balance", account=account)

    def account_info(self, account: str) -> dict:
        return self.call(action="account_info", account=account)

    def account_history(self, account: str, count: int = 10, offset: int = 0, sorting: str = "desc") -> dict:
        return self.call(action="account_history", account=account, count=count, offset=offset, sorting=sorting)

    def block_info(self, block_hash: str) -> dict:
        return self.call(action="block_info", hash=block_hash)

    def pending(self, account: str, count: int = 10) -> dict:
        return self.call(action="pending", account=account, count=count)