"""examples/spend_policy.py: the operator-side cap. Offline; no key, no node."""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples"))
import spend_policy as sp  # noqa: E402
from nano_sdk.crypto import address_from_public_key  # noqa: E402

A = address_from_public_key(bytes([1]) * 32)
B = address_from_public_key(bytes([2]) * 32)
C = address_from_public_key(bytes([3]) * 32)
XNO = 10 ** 30
DAY = 1_790_000_000 - (1_790_000_000 % 86400)       # 00:00 UTC of some day
POLICY_TEXT = "per_call_max_xno 0.01\ndaily_max_xno 0.025\nallow %s\nallow %s   # two receivers\n" % (A, B)


@pytest.fixture
def policy():
    return sp.parse_policy(POLICY_TEXT)


def req(i, to=A, amount=XNO // 200):
    return {"id": "r%s" % i, "to": to, "amount_raw": str(amount)}


def test_policy_needs_all_three_lines_and_defaults_none():
    for text in ("daily_max_xno 1\nallow %s" % A, "per_call_max_xno 1\nallow %s" % A, "per_call_max_xno 1\ndaily_max_xno 1"):
        with pytest.raises(sp.PolicyError):
            sp.parse_policy(text)


def test_policy_refuses_unknown_lines_floats_bad_addresses_and_inverted_caps():
    bad = ["per_call_max_xno 1e-3\ndaily_max_xno 1\nallow %s" % A,
           "per_call_max_xno 1\ndaily_max_xno 1\nallow nano_notanaddress",
           "per_call_max_xno 2\ndaily_max_xno 1\nallow %s" % A,
           "per_call_max_xno 1\ndaily_max_xno 1\nallow %s\nmax_everything 9" % A,
           "per_call_max_xno 0\ndaily_max_xno 1\nallow %s" % A,
           "per_call_max_xno 1\nper_call_max_xno 1\ndaily_max_xno 1\nallow %s" % A]
    for text in bad:
        with pytest.raises(sp.PolicyError):
            sp.parse_policy(text)


def test_within_policy_allows_and_reports_what_is_left(policy):
    d = sp.decide(policy, req(1), [], DAY + 10)
    assert d["allow"] and d["remaining_today_raw"] == str(25 * XNO // 1000 - XNO // 200)


def test_per_call_cap_is_exact_to_the_raw(policy):
    cap = XNO // 100
    assert sp.decide(policy, req(1, amount=cap), [], DAY)["allow"]
    d = sp.decide(policy, req(1, amount=cap + 1), [], DAY)
    assert (d["allow"], d["reason"]) == (False, "over_per_call_cap")


def test_daily_cap_counts_earlier_approvals_today_and_resets_at_utc_midnight(policy):
    done = [{"id": "p1", "amount_raw": str(XNO // 100), "at": DAY + 100}, {"id": "p2", "amount_raw": str(XNO // 100), "at": DAY + 200}]
    d = sp.decide(policy, req(9, amount=XNO // 200 + 1), done, DAY + 300)
    assert (d["allow"], d["reason"]) == (False, "over_daily_cap") and d["remaining_today_raw"] == str(XNO // 200)
    assert sp.decide(policy, req(9, amount=XNO // 200), done, DAY + 300)["allow"]                 # exactly the remainder
    assert sp.decide(policy, req(9, amount=XNO // 100), done, DAY + 86400 + 1)["allow"]            # next UTC day


def test_receiver_must_be_on_the_allow_list_in_either_spelling(policy):
    assert sp.decide(policy, req(1, to=C), [], DAY)["reason"] == "receiver_not_allowed"
    legacy = "xrb_" + B.split("_", 1)[1]
    assert sp.decide(policy, req(1, to=legacy), [], DAY)["allow"]


@pytest.mark.parametrize("amount", ["0", "-5", "1.5", "1e30", "", "abc", "9" * 40, 10, 1.5, None])
def test_malformed_amounts_are_refused(policy, amount):
    r = dict(req(1), amount_raw=amount)
    d = sp.decide(policy, r, [], DAY)
    assert d["allow"] is False and d["reason"] == "malformed_request"


def test_malformed_requests_are_refused(policy):
    for r in (None, [], {}, {"id": "", "to": A, "amount_raw": "1"}, {"id": "x", "to": "nano_bad", "amount_raw": "1"},
              {"id": "x" * 200, "to": A, "amount_raw": "1"}):
        assert sp.decide(policy, r, [], DAY)["allow"] is False


def test_a_repeated_request_id_is_not_paid_twice(policy):
    g = [{"id": "r1", "amount_raw": "5", "at": DAY}]
    assert sp.decide(policy, req(1), g, DAY + 1)["reason"] == "duplicate_request_id"


def test_gate_records_every_decision_before_answering_and_gives_the_signer_only_the_request(policy, tmp_path):
    gate = sp.Gate(policy, str(tmp_path / "ledger.jsonl"), clock=lambda: DAY + 5)
    ok = gate.handle(req(1))
    no = gate.handle(req(2, to=C))
    assert ok["allow"] and ok["sign_this"] == {"to": A, "amount_raw": str(XNO // 200), "id": "r1"}
    assert not no["allow"] and "sign_this" not in no
    lines = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [(l["id"], l["allow"]) for l in lines] == [("r1", True), ("r2", False)]
    assert oct(os.stat(tmp_path / "ledger.jsonl").st_mode & 0o777) == "0o600"


def test_a_denied_request_does_not_consume_the_cap(policy, tmp_path):
    gate = sp.Gate(policy, str(tmp_path / "l.jsonl"), clock=lambda: DAY + 5)
    gate.handle(req(1, to=C, amount=XNO // 100))
    assert gate.handle(req(2, amount=XNO // 100))["allow"]


def test_concurrent_requests_cannot_both_fit_under_one_remaining_cap(policy, tmp_path):
    gate = sp.Gate(policy, str(tmp_path / "l.jsonl"), clock=lambda: DAY + 5)
    out = []
    ts = [threading.Thread(target=lambda i=i: out.append(gate.handle(req(i, amount=XNO // 100)))) for i in range(16)]
    [t.start() for t in ts]; [t.join() for t in ts]
    allowed = [d for d in out if d["allow"]]
    assert len(allowed) == 2                                       # 0.025 daily / 0.01 each
    assert sum(1 for d in out if d.get("reason") == "over_daily_cap") == 14


def test_a_corrupt_ledger_fails_closed(policy, tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text("not json\n")
    assert sp.Gate(policy, str(p), clock=lambda: DAY).handle(req(1)) == {"allow": False, "reason": "ledger_unreadable"}
    p.write_text(json.dumps({"allow": True, "id": "a"}) + "\n")      # an allow with no amount cannot be counted
    assert sp.Gate(policy, str(p), clock=lambda: DAY).handle(req(2))["reason"] == "ledger_unreadable"


def test_the_example_holds_no_key_and_signs_nothing():
    import ast
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "spend_policy.py")
    tree = ast.parse(open(path).read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {node.module + "." + a.name for a in node.names}
    assert imported <= {"fcntl", "json", "os", "threading", "datetime.datetime", "datetime.timezone",
                        "nano_sdk.crypto.public_key_from_address", "nano_sdk.units.nano_to_raw"}, imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"sign", "sign_block", "Wallet", "derive", "seed", "process", "block_create", "urlopen", "post"}, names
