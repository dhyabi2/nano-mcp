"""A dollar quote must name the exact raw amount, and the same one everywhere.

`usd_to_xno_raw` did `(price_usd / rate_xno_usd) * RAW_PER_NANO` in the
*process-global* Decimal context. `prec` defaults to 28 significant digits and
this module never set it, while a raw amount reaches 39 -- so the division was
rounded at the 28th digit before the ceiling ever saw it, and
`to_integral_value(ROUND_CEILING)` cannot recover digits that are already gone.

Two consequences, both tested here:

  * the quote came out above OR below the true ceiling, and the below case is
    the one the function's own docstring promises cannot happen ("rounding UP so
    the seller never under-receives");
  * the amount depended on the Decimal context of whatever program imported
    nano_mcp. Nano has no memo, so the amount is the tag a payment is matched
    by; two sides computing it under different contexts do not agree.
"""
from decimal import Decimal, localcontext

import pytest

from nano_mcp.pricing import exact_xno_amount, usd_to_xno_raw


def exact_ceiling(price: str, rate: str) -> int:
    """ceil(price / rate * 10**30), computed independently of the code under test.

    Decimals are exact ratios of integers, so this is integer arithmetic only and
    consults no Decimal context.
    """
    p, r = Decimal(price), Decimal(rate)
    pn, pd = p.as_integer_ratio()
    rn, rd = r.as_integer_ratio()
    return -(-(pn * rd * 10**30) // (pd * rn))


# (price_usd, rate, what the shipped code produced, its error in raw)
MEASURED = [
    ("1.00", "0.34", 2941176470588235294117647059000, +176),
    ("1.00", "0.33", 3030303030303030303030303030000, -304),
    ("0.01", "0.8123", 12310722639418933891419426320, -1),
    ("0.05", "0.9876543", 50625001075781272860352048280, -3),
    ("2.50", "0.77", 3246753246753246753246753247000, +246),
]


@pytest.mark.parametrize("price,rate,was,err", MEASURED)
def test_a_dollar_quote_is_the_exact_ceiling(price, rate, was, err):
    want = exact_ceiling(price, rate)
    got = usd_to_xno_raw(Decimal(price), Decimal(rate))
    assert got == want, f"quoted {got}, exact ceiling is {want} ({got - want:+} raw)"
    # and the recorded measurement of the old behaviour is what it was
    assert was - want == err


@pytest.mark.parametrize("price,rate", [(p, r) for p, r, _, e in MEASURED if e < 0])
def test_the_seller_never_under_receives_which_is_the_documented_guarantee(price, rate):
    """The negative rows: the quote came in BELOW the true ceiling."""
    got = usd_to_xno_raw(Decimal(price), Decimal(rate))
    # the quote, in XNO, must be >= the USD price at this rate
    assert Decimal(got) * Decimal(rate) >= Decimal(price) * Decimal(10) ** 30


def test_the_quote_does_not_move_with_the_host_programs_decimal_context():
    """Same price, same rate, three host precisions, one answer."""
    answers = set()
    for prec in (6, 28, 40, 80):
        with localcontext() as ctx:
            ctx.prec = prec
            answers.add(usd_to_xno_raw(Decimal("1.00"), Decimal("0.34")))
    assert len(answers) == 1, f"the quoted amount moved with the host's prec: {answers}"
    assert answers.pop() == exact_ceiling("1.00", "0.34")


def test_a_full_precision_rate_survives_every_digit():
    """A rate naming 30 decimal places is used in full, not truncated at 28."""
    rate = "0.123456789012345678901234567891"
    got = usd_to_xno_raw(Decimal("1.00"), Decimal(rate))
    assert got == exact_ceiling("1.00", rate)
    # a rate differing only in its 30th decimal place must give a different quote
    other = "0.123456789012345678901234567892"
    assert got != usd_to_xno_raw(Decimal("1.00"), Decimal(other))


def test_the_exact_amount_reaches_the_quote_the_buyer_is_shown():
    """The fix has to arrive through exact_xno_amount, which is what quote_usd calls."""
    raw, rate = exact_xno_amount("1.00", rate_xno_usd=Decimal("0.33"))
    assert rate == Decimal("0.33")
    assert raw == exact_ceiling("1.00", "0.33")


# ---- controls: these must hold either way ----


def test_a_price_that_divides_exactly_is_unchanged():
    # 1.00 / 0.50 = 2 XNO exactly; nothing to round in any context
    assert usd_to_xno_raw(Decimal("1.00"), Decimal("0.50")) == 2 * 10**30
    assert usd_to_xno_raw(Decimal("0.001"), Decimal("1")) == 10**27


def test_a_sub_raw_quote_still_rounds_up_to_one_raw_not_to_zero():
    """A price so small it buys a fraction of a raw must still cost one raw, not
    nothing -- the ceiling is what keeps a quote from being free."""
    assert usd_to_xno_raw(Decimal("1E-40"), Decimal("1")) == 1


def test_non_positive_and_non_finite_are_refused():
    for bad_price in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError):
            usd_to_xno_raw(bad_price, Decimal("0.34"))
    for bad_rate in (Decimal("0"), Decimal("-0.34")):
        with pytest.raises(ValueError):
            usd_to_xno_raw(Decimal("1.00"), bad_rate)
    for bad in (Decimal("nan"), Decimal("Infinity")):
        with pytest.raises(ValueError):
            usd_to_xno_raw(bad, Decimal("0.34"))
        with pytest.raises(ValueError):
            usd_to_xno_raw(Decimal("1.00"), bad)


def test_the_decimal_context_does_not_leak():
    with localcontext() as ctx:
        ctx.prec = 11
        usd_to_xno_raw(Decimal("1.00"), Decimal("0.33"))
        assert ctx.prec == 11
