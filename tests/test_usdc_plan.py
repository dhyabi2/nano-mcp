"""plan_pay_from_usdc: offline. The replies are what api.nanswap.com answered on 2026-11-12, byte for byte."""
import json

import pytest

from nano_mcp import usdc_plan as u

SELLER = "nano_3z335ug5oz6sxfgcfz3kdqdrgn5otx7ht3epuc3kuimka6hc59xqem1jrzqy"
BUYER = "nano_1434j1n4sin4cefs5njibag4tsmo596fmg3s6bdogtod3ndmdfez5yuebrh9"
PRICE = "150000000000000000000000000000"          # 0.15 XNO, a real seller's per-call price that week

LIMITS = '{"min":0.171836,"max":3277.449183150415}'
ESTIMATE_5 = '{"amountTo":15.460743200506009,"amountFrom":5}'
TOO_SMALL = '{"error":true,"message":"Not available"}'
BAD_TICKER = '{"error":true,"message":"tickers not valid"}'


def wire(limits=LIMITS, estimate=ESTIMATE_5, seen=None):
    """A fetch that parses the pinned bytes exactly as the real one does."""
    def fetch(url):
        if seen is not None:
            seen.append(url)
        return json.loads(limits if "/get-limits" in url else estimate, parse_float=str)
    return fetch


def test_five_usdc_covers_a_fifteen_cent_xno_price_and_nothing_moves():
    seen = []
    plan = u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=wire(seen=seen))
    assert plan["covers"] is True and plan["moves_money"] is False
    assert plan["pay_with"] == "USDC-BASE" and plan["swap_lands_in"] == BUYER
    assert plan["estimated_raw"] == "15460743200506009" + "0" * 15      # the wire text, not a float's idea of it
    assert plan["needed_raw_with_headroom"] == "151500000000000000000000000000"
    assert int(plan["surplus_raw_kept_in_own_account"]) == int(plan["estimated_raw"]) - int(PRICE)
    assert seen == ["https://api.nanswap.com/v1/get-limits?from=USDC-BASE&to=XNO",
                    "https://api.nanswap.com/v1/get-estimate?from=USDC-BASE&to=XNO&amount=5"]


def test_the_limits_round_against_the_caller_never_for_them():
    plan = u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=wire())
    assert plan["provider_min_usdc"] == "0.171836"
    assert plan["provider_max_usdc"] == "3277.449183"                    # ...183150415 cut down, never up
    tight = u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=wire(limits='{"min":"0.1718361"}'))
    assert tight["provider_min_usdc"] == "0.171837" and tight["provider_max_usdc"] is None


def test_an_amount_under_the_minimum_is_answered_without_asking_for_an_estimate():
    seen = []
    plan = u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "0.05", fetch=wire(seen=seen))
    assert plan["covers"] is False and plan["estimated_raw"] is None
    assert "outside" in plan["why"] and len(seen) == 1


def test_an_estimate_one_raw_short_of_the_headroom_does_not_cover():
    needed = 151500000000000000000000000000
    for raw, covers in ((needed, True), (needed - 1, False)):
        whole, frac = divmod(raw, 10 ** 30)
        text = '{"amountTo":"%d.%030d"}' % (whole, frac)
        assert u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=wire(estimate=text))["covers"] is covers


def test_huge_and_absurd_amounts_are_refused_not_crashed_on():
    for text in ('{"amountTo":"1e999"}', '{"amountTo":"%s"}' % ("9" * 80), '{"amountTo":"0.%s1"}' % ("0" * 90)):
        with pytest.raises(u.PlanRefused):
            u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=wire(estimate=text))


def test_the_swap_may_not_be_pointed_at_the_seller():
    with pytest.raises(u.PlanRefused) as caught:
        u.plan_pay_from_usdc(SELLER, PRICE, SELLER, "5", fetch=wire())
    assert caught.value.reason == "swap_destination_is_payee"
    with pytest.raises(u.PlanRefused):                                   # the same account, legacy prefix
        u.plan_pay_from_usdc(SELLER, PRICE, "xrb_" + SELLER[5:], "5", fetch=wire())


@pytest.mark.parametrize("args,reason", [
    ((SELLER, "-1", BUYER, "5"), "invalid_amount"),
    ((SELLER, "1_000", BUYER, "5"), "invalid_amount"),
    ((SELLER, "0", BUYER, "5"), "invalid_amount"),
    ((SELLER, PRICE, BUYER, "5.0000001"), "invalid_amount"),
    ((SELLER, PRICE, BUYER, "0"), "invalid_amount"),
    ((SELLER, PRICE, BUYER, 5), "invalid_amount"),
    ((SELLER[:-1] + "x", PRICE, BUYER, "5"), "invalid_account"),
    ((SELLER, PRICE, "0xabc", "5"), "invalid_account"),
    ((SELLER, PRICE, BUYER, "5", ""), "invalid_network"),
    ((SELLER, PRICE, BUYER, "5", "BASE&to=BAN"), "invalid_network"),
])
def test_bad_input_is_refused_before_the_service_is_asked(args, reason):
    seen = []
    with pytest.raises(u.PlanRefused) as caught:
        u.plan_pay_from_usdc(*args, fetch=wire(seen=seen))
    assert caught.value.reason == reason and seen == []


def test_the_services_own_words_come_back_when_it_refuses():
    with pytest.raises(u.PlanRefused) as caught:
        u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", "NOPE", fetch=wire(limits=BAD_TICKER))
    assert caught.value.reason == "provider_refused" and "tickers not valid" in str(caught.value)
    with pytest.raises(u.PlanRefused) as caught:
        u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=wire(estimate=TOO_SMALL))
    assert "Not available" in str(caught.value)


@pytest.mark.parametrize("estimate", ['{"amountTo":true}', '{"amountTo":null}', '{}', '["15.4"]',
                                      '{"amountTo":"abc"}', '{"amountTo":"-1"}', '{"amountTo":"NaN"}'])
def test_a_reply_that_is_not_understood_is_refused_not_guessed(estimate):
    with pytest.raises(u.PlanRefused) as caught:
        u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=wire(estimate=estimate))
    assert caught.value.reason == "provider_response_unrecognised"


def test_a_float_from_a_careless_fetch_is_refused():
    with pytest.raises(u.PlanRefused):
        u.plan_pay_from_usdc(SELLER, PRICE, BUYER, "5", fetch=lambda url: {"min": 0.17, "amountTo": 15.46})


def test_the_command_line_exits_zero_only_when_the_amount_covers(monkeypatch, capsys):
    monkeypatch.setattr(u, "_fetch", wire())
    assert u.main([SELLER, PRICE, BUYER, "5"]) == 0
    assert json.loads(capsys.readouterr().out)["covers"] is True
    assert u.main([SELLER, PRICE, SELLER, "5"]) == 1
    assert json.loads(capsys.readouterr().out)["refused"] == "swap_destination_is_payee"
    assert u.main([SELLER]) == 2


def test_the_server_offers_the_tool_and_reports_a_refusal_in_words():
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError

    from nano_mcp.server import build_server
    from nano_mcp.service import PaymentService

    server = build_server(PaymentService())
    names = [t.name for t in asyncio.run(server.list_tools())]
    assert "plan_pay_from_usdc" in names
    with pytest.raises(ToolError) as caught:
        asyncio.run(server.call_tool("plan_pay_from_usdc", {
            "pay_to": SELLER, "amount_raw": PRICE, "own_account": SELLER, "usdc_amount": "5"}))
    assert "swap_destination_is_payee" in str(caught.value)
