"""Nano units: raw <-> nano.

1 nano = 10**30 raw. All RPC actions deal in integer raw amounts; floating point is never
used for money so no precision is ever lost.
"""
from decimal import Decimal

RAW_PER_NANO = Decimal("1000000000000000000000000000000")  # 10**30


def nano_to_raw(amount: str | Decimal | int) -> int:
    """Convert a nano amount (string or Decimal) to integer raw (10**30 scale).

    Raises ValueError if the amount has more than 30 decimal places or is negative.
    """
    d = Decimal(str(amount))
    if d < 0:
        raise ValueError("amount must be positive")
    raw = int(d * RAW_PER_NANO)
    if Decimal(raw) / RAW_PER_NANO != d:
        raise ValueError("amount has more precision than 10^-30 nano")
    return raw


def raw_to_nano(raw: int) -> Decimal:
    """Convert raw (10**30 scale) to a nano Decimal."""
    if not isinstance(raw, int):
        raise TypeError("raw must be an int")
    return Decimal(raw) / RAW_PER_NANO


def nano_str(raw: int) -> str:
    """Format raw as a plain decimal nano string (no exponent), e.g. '0.000001'."""
    return format(raw_to_nano(raw), "f")