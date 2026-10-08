"""Dollar-priced quotes: convert a USD price into an exact XNO amount using the
MEDIAN of three independent public price sources.

Stage-2 / strategy-law L2 design:
  * The seller prices a call in USD.
  * The service fetches the USD-per-XNO rate from THREE independent public
    sources (CoinGecko, CoinPaprika, Kucoin), takes the median, and converts the
    USD price to the exact integer raw XNO amount the buyer must pay.

No custody and no conversion: this module is PURE COMPUTATION. It never holds a
balance, never sends a block, never touches anyone's funds. The buyer pays the
returned exact raw XNO directly on-chain to the one-time payment address, and
the seller receives XNO on the chain — Rai never sits between or converts money.

Raw is always an integer (1 XNO = 10**30 raw). The USD -> raw conversion is done
in integer arithmetic rather than Decimal arithmetic, because Decimal rounds to
the active context precision (28 significant digits by default, against raw's
39) and that rounding is not recoverable by a later ceiling. The XNO amount is
rounded UP (ceiling) to the raw so the seller never under-receives the quoted USD
value at the quoted rate.

Sources are callables () -> Decimal so they are injectable for offline tests.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

import httpx

from nano_sdk.units import RAW_EXPONENT

# A dollar quote is honored only within this window from issue (<= 30s).
QUOTE_TTL_SECONDS = 30

# Each source returns USD per 1 XNO as a Decimal.
RateSource = Callable[[], Decimal]

_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=nano&vs_currencies=usd"
_COINPAPRIKA_URL = "https://api.coinpaprika.com/v1/tickers/xno-nano"
_KUCOIN_URL = "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=XNO-USDT"


def coingecko_xno_usd(timeout: float = 10.0) -> Decimal:
    data = httpx.get(_COINGECKO_URL, timeout=timeout).json()
    return Decimal(str(data["nano"]["usd"]))


def coinpaprika_xno_usd(timeout: float = 10.0) -> Decimal:
    data = httpx.get(_COINPAPRIKA_URL, timeout=timeout).json()
    return Decimal(str(data["quotes"]["USD"]["price"]))


def kucoin_xno_usd(timeout: float = 10.0) -> Decimal:
    data = httpx.get(_KUCOIN_URL, timeout=timeout).json()
    return Decimal(str(data["data"]["price"]))


DEFAULT_SOURCES: tuple[RateSource, ...] = (
    coingecko_xno_usd,
    coinpaprika_xno_usd,
    kucoin_xno_usd,
)


def median(values: list[Decimal]) -> Decimal:
    """Median of a list of Decimal rates: middle value of the sorted list (for an\
    odd count this is the middle element; for an even count, the mean of the two\
    middle values)."""
    if not values:
        raise ValueError("no price source returned a rate")
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    mid = n // 2
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def fetch_median_xno_usd(sources: tuple[RateSource, ...]) -> Decimal:
    """Return the median USD-per-XNO rate across `sources`, tolerating a single
    source failure and requiring at least 2 healthy sources (so one API outage
    cannot skew the median into a bad quote)."""
    rates: list[Decimal] = []
    for src in sources:
        try:
            rates.append(Decimal(str(src())))
        except Exception:
            continue
    if len(rates) < 2:
        raise RuntimeError(f"fewer than 2 price sources available ({len(rates)}/3)")
    return median(rates)


def usd_to_xno_raw(price_usd: Decimal, rate_xno_usd: Decimal) -> int:
    """Convert a USD price to the exact integer raw XNO amount at `rate_xno_usd`
    (USD per XNO), rounding UP so the seller never under-receives.

    raw_xno = ceil(price_usd / rate_xno_usd * 10**30)

    Computed in **integer** arithmetic, not Decimal arithmetic. `price / rate` is
    usually a non-terminating decimal, and Decimal rounds every operation to the
    active context precision -- which defaults to 28 significant digits, while a
    raw amount reaches 39. So the old `(price / rate) * RAW_PER_NANO` was rounded
    at the 28th digit before `to_integral_value(ROUND_CEILING)` ever saw it, and
    the ceiling could not recover what the division had already thrown away:
    ($1.00, 0.34) quoted 176 raw too much, ($1.00, 0.33) **304 raw too little** --
    the direction this function's own docstring promises cannot happen.

    It was also not self-contained: nothing here sets the context, so the quoted
    amount moved with the `prec` of whatever program imported `nano_mcp`
    (...059000 at 28, ...058824 at 40). Nano has no memo, so the amount is the
    tag a payment is matched by; two sides computing it under different contexts
    do not agree on the number.

    Every Decimal is an exact ratio of integers, so the ceiling is computed
    exactly from those ratios and no context is consulted at all.
    """
    price = Decimal(str(price_usd))
    rate = Decimal(str(rate_xno_usd))
    if not price.is_finite() or not rate.is_finite():
        raise ValueError(
            f"price and rate must be finite numbers: {price_usd!r}, {rate_xno_usd!r}"
        )
    if price <= 0:
        raise ValueError("price_usd must be positive")
    if rate <= 0:
        raise ValueError("rate_xno_usd must be positive")
    price_num, price_den = price.as_integer_ratio()
    rate_num, rate_den = rate.as_integer_ratio()
    numerator = price_num * rate_den * 10**RAW_EXPONENT
    denominator = price_den * rate_num
    # ceiling division on integers: -(-a // b)
    return -(-numerator // denominator)


def exact_xno_amount(
    price_usd: str | Decimal,
    sources: tuple[RateSource, ...] = DEFAULT_SOURCES,
    rate_xno_usd: Decimal | None = None,
) -> tuple[int, Decimal]:
    """Compute (exact_raw_xno, median_rate) for a USD price.

    Pass `rate_xno_usd` to fix the rate (offline tests); otherwise the median of
    `sources` is fetched live.
    """
    price = Decimal(str(price_usd))
    rate = rate_xno_usd if rate_xno_usd is not None else fetch_median_xno_usd(sources)
    return usd_to_xno_raw(price, rate), rate


def default_rate() -> Decimal:
    """Live USD-per-XNO median across the three default public sources."""
    return fetch_median_xno_usd(DEFAULT_SOURCES)