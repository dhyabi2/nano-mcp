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
from .client import RpcClient, representative_from_info
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
    # None (the default) means "keep whatever representative the account already
    # has": a send carries the node-reported representative into the block, and
    # only an account with none (unopened, or a blank answer) gets
    # DEFAULT_REPRESENTATIVE. A representative passed here explicitly is used for
    # every send instead, re-delegating the account to it. After construction
    # this attribute always reads as an address (the default when none was
    # passed), so existing code that reads `wallet.representative` keeps working.
    representative: str | None = None
    # Per-wallet rolling spend tracker: daytime-epoch -> raw sent that day.
    _spend: dict[int, int] = field(default_factory=dict)
    _day: int = field(default_factory=lambda: int(time.time()) // 86400)
    _representative_explicit: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._representative_explicit = self.representative is not None
        if self.representative is None:
            self.representative = DEFAULT_REPRESENTATIVE

    def _send_representative(self, info: dict) -> str:
        """The representative a send from this account signs into its block.

        A caller-chosen representative wins (set at construction, or assigned to
        `wallet.representative` later). Otherwise the account keeps the one the
        node reports, validated (RpcError if malformed), falling back to
        DEFAULT_REPRESENTATIVE when the node reports none.

        The one case the sentence above does not cover: a wallet built with no
        representative and later ASSIGNED exactly DEFAULT_REPRESENTATIVE is
        indistinguishable from one that never set it -- an assignment leaves no
        other trace than the value, and the value is the default. Such a wallet
        keeps the account's current representative. Re-delegating to the default
        on purpose means passing it to the constructor, where the explicit flag
        records it. Pinned by
        tests/test_send_keeps_the_representative.py::test_assigning_the_default_representative_is_not_an_explicit_choice,
        so the README and this cannot drift from the code again.
        """
        if self._representative_explicit or self.representative != DEFAULT_REPRESENTATIVE:
            rep = self.representative
            if not validate_address(rep):
                raise ValueError(f"representative is not a valid nano_ address: {rep!r}")
            return rep
        return representative_from_info(info) or DEFAULT_REPRESENTATIVE

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
        """Raise if `amount_raw` is not raw, overdraws `balance_raw`, or the daily cap.

        The type check comes first because this is the guard that runs before
        anything is signed or published. Raw is an integer count (1 XNO = 10**30
        raw) and nothing else will do: a float has no exact representation at that
        scale, and `block.py` only noticed one inside
        `balance_raw.to_bytes(16, "big")` -- an AttributeError, raised after a
        `work_generate` round-trip had already been spent. `bool` is excluded
        explicitly because it is a subclass of `int`: `True > 0` passed every guard
        below and `balance - True` published a real send of 1 raw.
        """
        if isinstance(amount_raw, bool) or not isinstance(amount_raw, int):
            raise ValueError(
                "amount must be an integer count of raw (1 XNO = 10**30 raw), "
                f"not {type(amount_raw).__name__}: {amount_raw!r}"
            )
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
        # Decided (and the node's answer validated) here, before work_generate is
        # requested or anything is signed. The node omits the key for an
        # unopened account, and a blank answer falls back rather than reaching
        # `public_key_from_address`; see `_send_representative`.
        rep = self._send_representative(info)
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
