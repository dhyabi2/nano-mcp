"""plan_pay_from_usdc: can a wallet that holds only USDC pay this XNO price, and with how much?

A seller's 402 asks for an exact amount of raw to a nano_ address. Most agents that buy over x402 hold USDC and
no XNO, so the price cannot be paid as asked. This answers, read-only, what the hop would take today:

    USDC  --(swap service)-->  XNO in the agent's OWN account  --(send)-->  seller

It asks Nanswap's public quote endpoints (no key, no account) for the pair's limits and for what `usdc_amount`
yields, and says whether that covers the price plus 1% headroom. **It moves nothing**: no order is created, no
key is read, nothing is signed. Stdlib only.

What it refuses, and why:
  - `own_account` equal to `pay_to`: pointing the swap straight at the seller looks like it saves a step, and it
    breaks the payment - the service sends whatever the swap yielded, not the exact raw the 402 asked for, from
    the service's account, so the seller cannot match it to the call.
  - a network left out: USDC lives on many chains, and USDC sent on the wrong one does not come back.
  - anything the service answers that is not understood: a field is never defaulted.

Measured against the live API on 2026-11-12; the real replies are pinned in tests/test_usdc_plan.py. Amounts are
read as their exact text on the wire and handled as integers - a float never holds an XNO amount here.

Doing the hop (creating the order needs a Nanswap API key, and the swap is custodial while it runs) is not this
tool: see https://github.com/dhyabi2/agent-wallet-multirail (`pay_nano_quote_from_usdc`), which records the order
so a retry cannot buy it twice and sends the seller the exact raw.

  python3 nano_mcp/usdc_plan.py PAY_TO AMOUNT_RAW OWN_ACCOUNT USDC_AMOUNT [NETWORK]   # stdlib only
Exit 0 when the amount covers the price, 1 otherwise.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, InvalidOperation

try:  # the same checksum check verify_block_multi uses; a bare `python3 nano_mcp/usdc_plan.py` has no package
    from .verify_multi import account_to_pubkey
except ImportError:  # pragma: no cover - script mode
    from verify_multi import account_to_pubkey  # type: ignore

API = "https://api.nanswap.com/v1"
#: Cloudflare in front of the API answers 403 to urllib's default User-Agent (measured 2026-11-12).
USER_AGENT = "nano-mcp (+https://github.com/dhyabi2/nano-mcp)"
RAW_PER_XNO = 10 ** 30
MICRO = 10 ** 6
HEADROOM_BPS = 100          # the estimate must clear the price by 1%: an estimate is not a firm quote
MAX_RAW = 2 ** 128 - 1
#: Decimal's default context keeps 28 digits and an XNO amount in raw has up to 39: every operation on a
#: provider's number goes through this one, or the last digits are silently rounded away.
_EXACT = Context(prec=120)


class PlanRefused(ValueError):
    """The plan cannot be made. `reason` is a stable word; the message says what to change."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _fetch(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as reply:
            text = reply.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise PlanRefused("provider_unreachable", "the swap service could not be read (%s)" % exc) from exc
    try:
        return json.loads(text, parse_float=str)     # a number stays the exact text that was sent
    except ValueError as exc:
        raise PlanRefused("provider_response_unrecognised",
                          "the swap service's reply is not JSON: %r" % text[:120]) from exc


def _ask(fetch, path: str, params: dict) -> dict:
    reply = fetch("%s%s?%s" % (API, path, urllib.parse.urlencode(params)))
    if not isinstance(reply, dict):
        raise PlanRefused("provider_response_unrecognised",
                          "%s answered %s, not an object" % (path, type(reply).__name__))
    if reply.get("error"):
        said = reply.get("message") if isinstance(reply.get("message"), str) else reply.get("error")
        raise PlanRefused("provider_refused", "%s: the swap service answered %r" % (path, said))
    return reply


def _decimal(reply: dict, name: str, path: str) -> Decimal:
    value = reply.get(name)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise PlanRefused("provider_response_unrecognised",
                          "%s: %r is %s, not an exact amount" % (path, name, type(value).__name__))
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise PlanRefused("provider_response_unrecognised",
                          "%s: %r is not a decimal amount (%r)" % (path, name, value)) from exc
    if not number.is_finite() or number < 0 or number.adjusted() > 40 or -number.as_tuple().exponent > 60:
        raise PlanRefused("provider_response_unrecognised", "%s: %r is not usable (%r)" % (path, name, value))
    return number


def _scaled(number: Decimal, unit: int, rounding) -> int:
    """`number` x `unit` as an integer, rounded the given way, with no digit lost on the way."""
    return int(_EXACT.multiply(number, Decimal(unit)).to_integral_value(rounding=rounding, context=_EXACT))


def _usdc_micro(text) -> int:
    ok = isinstance(text, str) and text.strip().isascii()
    whole, dot, frac = (text.strip() if ok else "").partition(".")
    if not ok or not (whole or frac) or not (whole or "0").isdigit() or (dot and not frac.isdigit()) or len(frac) > 6:
        raise PlanRefused("invalid_amount", "usdc_amount must be a decimal string with at most 6 decimals, "
                                            "such as '5' or '0.50' (got %r)" % (text,))
    micro = int(whole or "0") * MICRO + int(frac.ljust(6, "0") or "0")
    if micro <= 0:
        raise PlanRefused("invalid_amount", "usdc_amount must be greater than zero (got %r)" % (text,))
    return micro


def _usdc(micro: int) -> str:
    whole, frac = divmod(micro, MICRO)
    return ("%d.%06d" % (whole, frac)).rstrip("0").rstrip(".")


def _account(value, name: str) -> str:
    try:
        account_to_pubkey(value)
    except (ValueError, TypeError) as exc:
        raise PlanRefused("invalid_account", "%s is not a valid nano_ account (%r)" % (name, value)) from exc
    return value


def plan_pay_from_usdc(pay_to: str, amount_raw: str, own_account: str, usdc_amount: str,
                       network: str = "BASE", fetch=None) -> dict:
    """Read-only plan for paying `amount_raw` to `pay_to` from USDC on `network`. Raises PlanRefused."""
    fetch = fetch or _fetch
    if not (isinstance(amount_raw, str) and amount_raw.isascii() and amount_raw.isdigit()) \
            or not 0 < int(amount_raw) <= MAX_RAW:
        raise PlanRefused("invalid_amount", "amount_raw must be a whole number of raw in ASCII digits, "
                                            "as the 402 gives it (got %r)" % (amount_raw,))
    price_raw = int(amount_raw)
    pay_to, own_account = _account(pay_to, "pay_to"), _account(own_account, "own_account")
    if account_to_pubkey(pay_to) == account_to_pubkey(own_account):
        raise PlanRefused("swap_destination_is_payee",
                          "own_account is the seller's account. The swap must land in YOUR account and the exact "
                          "raw is then sent on: a swap pointed at the seller delivers what it yielded, not the "
                          "price, from the swap service's account")
    net = network.strip().upper() if isinstance(network, str) else ""
    if not net.isalnum():
        raise PlanRefused("invalid_network", "name the chain the USDC is on, such as 'BASE' (got %r)" % (network,))
    ticker = "USDC-" + net
    spend = _usdc_micro(usdc_amount)

    limits = _ask(fetch, "/get-limits", {"from": ticker, "to": "XNO"})
    minimum = _scaled(_decimal(limits, "min", "/get-limits"), MICRO, ROUND_CEILING)
    maximum = None
    if limits.get("max") is not None:
        maximum = _scaled(_decimal(limits, "max", "/get-limits"), MICRO, ROUND_FLOOR)

    needed_raw = -(-price_raw * (10000 + HEADROOM_BPS) // 10000)
    out = {
        "moves_money": False,
        "pay_to": pay_to, "amount_raw": str(price_raw),
        "swap_lands_in": own_account,
        "pay_with": ticker, "usdc_amount": _usdc(spend),
        "provider": "nanswap", "provider_min_usdc": _usdc(minimum),
        "provider_max_usdc": None if maximum is None else _usdc(maximum),
        "needed_raw_with_headroom": str(needed_raw), "headroom_bps": HEADROOM_BPS,
    }
    if spend < minimum or (maximum is not None and spend > maximum):
        out.update(covers=False, estimated_raw=None,
                   why="usdc_amount is outside what the swap service takes for this pair "
                       "(%s to %s USDC)" % (out["provider_min_usdc"], out["provider_max_usdc"] or "no stated maximum"))
        return out

    estimate = _ask(fetch, "/get-estimate", {"from": ticker, "to": "XNO", "amount": _usdc(spend)})
    estimated_raw = _scaled(_decimal(estimate, "amountTo", "/get-estimate"), RAW_PER_XNO, ROUND_FLOOR)
    covers = estimated_raw >= needed_raw
    out.update(covers=covers, estimated_raw=str(estimated_raw),
               surplus_raw_kept_in_own_account=str(max(0, estimated_raw - price_raw)) if covers else None,
               why=("the estimate covers the price plus headroom" if covers else
                    "the estimate is short of the price plus headroom: raise usdc_amount"),
               steps=[
                   "create a swap order %s -> XNO paying out to swap_lands_in (needs a Nanswap API key)" % ticker,
                   "check the order names %s and pays out to swap_lands_in, then fund its pay-in address" % ticker,
                   "when the XNO has arrived, send exactly amount_raw to pay_to and present that block",
               ],
               caution="an estimate is not a firm quote, and the swap is custodial while it runs")
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not 4 <= len(argv) <= 5:
        print(__doc__.strip().splitlines()[-2].strip(), file=sys.stderr)
        return 2
    try:
        plan = plan_pay_from_usdc(*argv)
    except PlanRefused as exc:
        print(json.dumps({"refused": exc.reason, "message": str(exc)}, indent=2))
        return 1
    print(json.dumps(plan, indent=2))
    return 0 if plan["covers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
