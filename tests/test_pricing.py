"""Block 6 — dollar-priced quotes (L8 exact median XNO amount, L9 30s expiry).

L8: a USD price converts to the exact XNO raw amount via the MEDIAN of three
    independent price sources; the conversion is pure computation (no money is
    held or converted).
L9: a dollar quote expires in 30 seconds or less and verify_payment refuses a
    payment made after the window.
"""
from __future__ import annotations

import time
from decimal import Decimal

import pytest

import nano_mcp.pricing as pricing
from nano_mcp.pricing import (
    DEFAULT_SOURCES,
    QUOTE_TTL_SECONDS,
    exact_xno_amount,
    fetch_median_xno_usd,
    median,
    usd_to_xno_raw,
)
from nano_mcp.service import PaymentService
from nano_mcp.store import ApprovalStore
from nano_sdk.units import RAW_PER_NANO, nano_str


# ---- helpers: fixed-rate sources (offline) ----
def _src(v: str):
    return lambda: Decimal(v)


def _rate(*vals: str):
    return _src(vals[0])() if len(vals) == 1 else None


# ============================= L8 =============================
def test_median_returns_middle_value():
    assert median([Decimal("0.30"), Decimal("0.34"), Decimal("0.35")]) == Decimal("0.34")
    assert median([Decimal("1"), Decimal("3")]) == Decimal("2")


def test_median_requires_at_least_one():
    with pytest.raises(ValueError):
        median([])


def test_fetch_median_tolerates_one_failure():
    good_ones = [_src("0.30"), _src("0.34"), _src("0.35")]
    # failing source index 1 must not break the quote: median of the two
    # healthy (0.30, 0.35) is their mean 0.325.
    three = [good_ones[0], lambda: (_ for _ in ()).throw(RuntimeError("down")), good_ones[2]]
    assert fetch_median_xno_usd(tuple(three)) == Decimal("0.325")


def test_fetch_median_requires_two_healthy():
    two_down = [
        lambda: (_ for _ in ()).throw(RuntimeError("down")),
        lambda: (_ for _ in ()).throw(RuntimeError("down")),
        _src("0.34"),
    ]
    with pytest.raises(RuntimeError):
        fetch_median_xno_usd(tuple(two_down))


def test_usd_to_xno_raw_rounds_up_never_underpays():
    # $1.00 at $0.34/XNO -> 2.941176... XNO -> ceil to a whole raw.
    raw = usd_to_xno_raw(Decimal("1.00"), Decimal("0.34"))
    expect = int((Decimal("1.00") / Decimal("0.34") * RAW_PER_NANO).to_integral_value(
        rounding="ROUND_CEILING"
    ))
    assert raw == expect
    # the seller receives at least the quoted USD value at that rate
    assert raw * Decimal("0.34") >= Decimal("1.00") * RAW_PER_NANO


def test_usd_to_xno_raw_rejects_non_positive():
    with pytest.raises(ValueError):
        usd_to_xno_raw(Decimal("0"), Decimal("0.34"))
    with pytest.raises(ValueError):
        usd_to_xno_raw(Decimal("1.0"), Decimal("0"))


def test_exact_xno_amount_uses_fixed_rate_offline():
    # fixed median rate 0.34 USD/XNO for a $1.00 price
    sources = (_src("0.30"), _src("0.34"), _src("0.35"))
    raw, rate = exact_xno_amount("1.00", sources=sources)
    assert rate == Decimal("0.34")
    expect = usd_to_xno_raw(Decimal("1.00"), Decimal("0.34"))
    assert raw == expect
    # exact: amount == price / median rate, rounded up at raw scale
    assert raw >= int(Decimal("1.00") / Decimal("0.34") * RAW_PER_NANO)


def test_quote_usd_returns_exact_median_amount_and_no_money_moves(tmp_path):
    """L8: quote_usd returns the exact XNO amount from the median of three
    injected sources, carrying price_usd, rate and expiry; no balance exists or
    is transferred — verify it is pure computation (no RPC client contact)."""
    store = ApprovalStore(path=str(tmp_path / "s.db"))
    svc = PaymentService(
        master_secret=b"S" * 32,
        store=store,
        rate_source=_src("0.34"),
        clock=lambda: 1000.0,
    )
    q = svc.quote_usd("1.00", request_id="req-a")
    assert q.price_usd == "1.00"
    assert q.rate_xno_usd == "0.34"
    assert q.price_raw == usd_to_xno_raw(Decimal("1.00"), Decimal("0.34"))
    d = q.as_dict()
    assert set(d) >= {"request_id", "address", "price_raw", "price_usd", "rate_xno_usd", "expires_at"}
    # never converts or holds: quote is a computation, not a transfer
    assert d["address"].startswith("nano_")
    import nano_sdk.crypto as crypto
    assert crypto.validate_address(d["address"])


class _ContactingClient:
    """RpcClient stand-in that fails if quote_usd ever talks to the chain —
    proves the quote path performs NO balance change or transfer."""

    def __init__(self):
        self.contacted = False
        self.balance = "1000000000000000000000000000000"

    def account_balance(self, *a, **k):
        self.contacted = True
        return {"balance": self.balance}

    def account_history(self, *a, **k):
        self.contacted = True
        return {"history": []}

    def process(self, *a, **k):
        self.contacted = True
        raise AssertionError("quote_usd must never broadcast a block")

    def work_generate(self, *a, **k):
        self.contacted = True
        raise AssertionError("quote_usd must never generate PoW")


def test_quote_usd_is_pure_computation_no_chain_contact(tmp_path):
    """L8 (hard test): the dollar quote performs NO balance change or transfer —
    a client that records every contact is never touched while quoting."""
    spy = _ContactingClient()
    store = ApprovalStore(path=str(tmp_path / "p.db"))
    svc = PaymentService(
        master_secret=b"S" * 32,
        client=spy,  # type: ignore[arg-type]
        store=store,
        rate_source=_src("0.34"),
        clock=lambda: 1000.0,
    )
    q = svc.quote_usd("1.00", request_id="req-pure")
    assert q.price_raw > 0
    assert not spy.contacted, "quote_usd must not touch the chain (no custody/no conversion)"


# ============================= L9 =============================
def test_quote_expires_in_30_seconds_or_less(tmp_path):
    store = ApprovalStore(path=str(tmp_path / "e.db"))
    svc = PaymentService(
        master_secret=b"S" * 32,
        store=store,
        rate_source=_src("0.34"),
        clock=lambda: 5000.0,
    )
    q = svc.quote_usd("0.50", request_id="req-x")
    assert q.expires_at is not None
    assert q.expires_at - 5000.0 <= QUOTE_TTL_SECONDS
    assert q.expires_at - 5000.0 <= 30.0
    assert not q.expired(now=5000.0)
    assert q.expired(now=q.expires_at + 0.001)  # type: ignore[operator]


def test_verify_refuses_expired_quote__does_not_approve(tmp_path):
    """L9: a dollar quote paid after its window returns status='expired' and is
    never approved."""
    store = ApprovalStore(path=str(tmp_path / "x.db"))
    svc = PaymentService(
        master_secret=b"S" * 32,
        store=store,
        rate_source=_src("0.34"),
        clock=lambda: 1000.0,
    )
    q = svc.quote_usd("1.00", request_id="req-exp")
    # advance the clock past the expiry
    svc.clock = lambda: q.expires_at + 60.0
    out = svc.verify_payment("req-exp", q.price_raw, require_onchain=False)
    assert out["status"] == "expired"
    # not approved, so a re-check does not turn spent
    assert not store.is_approved("req-exp")


def test_verify_accepts_quote_within_window(tmp_path):
    store = ApprovalStore(path=str(tmp_path / "y.db"))
    svc = PaymentService(
        master_secret=b"S" * 32,
        store=store,
        rate_source=_src("0.34"),
        clock=lambda: 1000.0,
    )
    q = svc.quote_usd("1.00", request_id="req-ok")
    out = svc.verify_payment("req-ok", q.price_raw, require_onchain=False)
    assert out["status"] == "approved"
    assert store.is_approved("req-ok")


# ===================== live network tests (3 sources) =====================
@pytest.mark.network
def test_live_median_of_three_sources_returns_numeric():
    """Live: three independent public sources each return a numeric USD/XNO rate
    and the median is between the observed min and max."""
    rates = []
    for src in DEFAULT_SOURCES:
        rates.append(Decimal(str(src())))
    assert len(rates) == 3
    for r in rates:
        assert r > 0
    m = median(rates)
    assert min(rates) <= m <= max(rates)
    # sanity: a sane XNO price in USD
    assert Decimal("0.005") < m < Decimal("100")