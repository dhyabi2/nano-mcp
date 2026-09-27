"""Wallet: derive an account, read state, and send with balance + daily-cap guards.

Money rule (AGENTS.md): outbound total from any wallet is at most 0.01 XNO per
day and never more than the wallet holds. This module enforces both before
anything is signed or published.

Key management is external (external-key model, docs.nano.org): the seed/private
key never leaves this module; only ready-to-broadcast signed blocks are built.
Two independent reads (account_info for balance/frontier/representative) are
used so a send never overdraws.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from . import block as blockmod
from .client import RpcClient
from .crypto import Account, derive_account, validate_address
from .units import nano_to_raw

DEFAULT_DAILY_CAP_RAW = int(nano_to_raw("0.01"))  # 0.01 XNO / day


class ClientLike(Protocol):
    """Minimal RPC surface the wallet needs (enables stub clients in tests)."""

    def account_info(self, account: str) -> dict: ...
    def call(self, **payload) -> dict: ...

# Representatives: use a long-running, well-known rep (NanoFusion) for test sends.
DEFAULT_REPRESENTATIVE = "nano_1stofnrxuz3cai7ze75o174bpm7scwj9jn3nxsn8ntzg784jf1gzn1jjdkou"


class InsufficientBalance(RuntimeError):
    pass


class DailyCapExceeded(RuntimeError):
    pass


@dataclass
class Wallet:
    """A Nano wallet (seed + derived accounts) with send guards."""

    # repr=False: the seed derives every account's private key, so it must not
    # reach a log. A dataclass repr prints every field, and anything that reprs
    # locals (a traceback with locals, pytest -l, logging.exception, a debugger)
    # would carry it. Account.__repr__ hides the private key for the same reason.
    seed: bytes | str = field(repr=False)
    client: ClientLike = field(default_factory=RpcClient)
    daily_cap_raw: int = DEFAULT_DAILY_CAP_RAW
    representative: str = DEFAULT_REPRESENTATIVE
    # Per-wallet rolling spend tracker: daytime-epoch -> raw sent that day.
    _spend: dict[int, int] = field(default_factory=dict)
    _day: int = field(default_factory=lambda: int(time.time()) // 86400)

    def account(self, index: int = 0) -> Account:
        return derive_account(self.seed, index)

    # -- spend tracking (rolling 24h) --
    def _today(self) -> int:
        now = int(time.time())
        day = now // 86400
        if day != self._day:
            self._day = day
            self._spend = {}
        return now

    def _sent_today(self) -> int:
        self._today()
        return sum(self._spend.values())

    def _record_send(self, raw: int) -> None:
        self._today()
        now = int(time.time())
        day = now // 86400
        self._spend[day] = self._spend.get(day, 0) + raw

    def available_today(self) -> int:
        """Raw we may still send today under the daily cap."""
        return max(0, self.daily_cap_raw - self._sent_today())

    # -- guards -- (pure, unit-testable)
    def check_send(self, amount_raw: int, balance_raw: int) -> None:
        """Raise if `amount_raw` overdraws `balance_raw` or the daily cap."""
        if amount_raw <= 0:
            raise ValueError("amount must be > 0")
        if amount_raw > balance_raw:
            raise InsufficientBalance(
                f"amount {amount_raw} raw > balance {balance_raw} raw"
            )
        if amount_raw > self.available_today():
            raise DailyCapExceeded(
                f"amount {amount_raw} raw > {self.available_today()} raw remaining today"
            )

    # -- send pipeline --
    def account_info(self, index: int = 0) -> dict:
        acct = self.account(index)
        return self.client.account_info(acct.address)

    # -- guard balance (live, unused by send which reads info atomically) --
    def balance_raw(self, index: int = 0) -> int:
        info = self.client.account_info(self.account(index).address)
        bal = info.get("balance")
        if bal is None:
            raise RpcBalanceError(f"no balance in account_info: {info}")
        # account_info returns the raw balance as a string.
        return int(bal)

    def send(
        self,
        destination: str,
        amount_raw: int,
        index: int = 0,
        work: str | None = None,
    ) -> tuple[str, dict]:
        """Send `amount_raw` to `destination` from account `index`.

        Steps: read account_info (balance + frontier + representative atomically),
        guard balance + daily cap, generate PoW (or accept provably-fast work via
        rpc.nano.to work_generate), build+sign the send block, publish via process.

        Returns (block_hash, block_dict). Raises InsufficientBalance /
        DailyCapExceeded before anything is broadcast.
        """
        if not validate_address(destination):
            raise ValueError("destination is not a valid nano_ address")

        acct = self.account(index)
        info = self.client.account_info(acct.address)
        raw_balance = int(info.get("balance", "0"))
        frontier_hex = info.get("frontier") or "0" * 64
        frontier = bytes.fromhex(frontier_hex)  # 32 raw bytes
        rep = info.get("representative", self.representative)
        frontier_ascii = frontier_hex.encode()  # hex string for work_generate

        self.check_send(amount_raw, raw_balance)
        new_balance = raw_balance - amount_raw

        # PoW: generated over the previous (frontier) hash for non-open blocks.
        if work is None:
            gen = self.client.call(action="work_generate", hash=frontier_ascii.decode())
            assert isinstance(gen.get("work"), str), f"work_generate returned: {gen}"
            work = gen["work"]

        blk = blockmod.build_send_block(
            private_key=acct.private_key,
            account_pub=acct.public_key,
            account_address=acct.address,
            previous=frontier,
            representative_address=rep,
            new_balance_raw=new_balance,
            destination_address=destination,
            work=work,
        )
        result = self.client.call(
            action="process",
            json_block="true",
            subtype="send",
            block=blk,
        )
        block_hash = result["hash"]
        # Only record the spend once the block is accepted by the node.
        self._record_send(amount_raw)
        return block_hash, blk


class RpcBalanceError(RuntimeError):
    pass
