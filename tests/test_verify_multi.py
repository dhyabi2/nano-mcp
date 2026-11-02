"""verify_block_multi: pure and offline. The fixture is a real confirmed send read from rpc.nano.to (2026-11-02)."""
import copy, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "nano_mcp"))
import verify_multi as v  # stdlib-only module, loaded by path so the test needs no httpx/mcp

INFO = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures_block_info.json")))
H = "B749B757EE750FC9AEA72F33CB429EACCD2ABEC9F2CCF59BF17AFAC304C9A58F"
NODES = ("https://a", "https://b", "https://c")


def fetcher(replies):
    def f(url, body):
        r = replies[url]
        if isinstance(r, Exception):
            raise r
        return r
    return f


def test_hash_is_recomputed_from_contents():
    assert v.state_block_hash(INFO["contents"]) == H


def test_three_agreeing_nodes_pass_and_the_node_set_is_listed():
    r = v.verify_block_multi(H, NODES, fetch=fetcher({u: INFO for u in NODES}))
    assert r["verdict"] == "pass" and r["agreeing_nodes"] == list(NODES) and len(r["nodes"]) == 3


def test_two_of_three_is_not_enough_by_default():
    rep = {NODES[0]: INFO, NODES[1]: INFO, NODES[2]: OSError("down")}
    r = v.verify_block_multi(H, NODES, fetch=fetcher(rep))
    assert r["verdict"] == "fail" and "2 of the required 3" in r["why"]
    assert v.verify_block_multi(H, NODES, min_agree=2, fetch=fetcher(rep))["verdict"] == "pass"


def test_a_node_that_changes_a_field_is_caught_by_the_hash():
    bad = copy.deepcopy(INFO)
    bad["contents"]["balance"] = str(int(bad["contents"]["balance"]) + 1)
    r = v.verify_block_multi(H, NODES, fetch=fetcher({NODES[0]: INFO, NODES[1]: INFO, NODES[2]: bad}))
    assert r["verdict"] == "fail" and "do not hash" in r["why"]


def test_unconfirmed_is_not_agreement():
    unc = dict(INFO, confirmed="false")
    r = v.verify_block_multi(H, NODES, fetch=fetcher({NODES[0]: INFO, NODES[1]: INFO, NODES[2]: unc}))
    assert r["verdict"] == "fail"


def test_missing_block_is_ignorance_not_contradiction():
    rep = {NODES[0]: INFO, NODES[1]: INFO, NODES[2]: {"error": "Block not found"}}
    r = v.verify_block_multi(H, NODES, min_agree=2, fetch=fetcher(rep))
    assert r["verdict"] == "pass"


def test_wrong_payee_or_amount_fails():
    f = fetcher({u: INFO for u in NODES})
    assert v.verify_block_multi(H, NODES, payee=INFO["contents"]["account"], fetch=f)["verdict"] == "fail"
    assert v.verify_block_multi(H, NODES, amount_raw="1", fetch=f)["verdict"] == "fail"
    ok = v.verify_block_multi(H, NODES, payee=INFO["contents"]["link_as_account"], amount_raw=INFO["amount"], fetch=f)
    assert ok["verdict"] == "pass"


def test_malformed_hash_asks_no_node():
    called = []
    r = v.verify_block_multi("zz", NODES, fetch=lambda u, b: called.append(u))
    assert r["verdict"] == "fail" and called == []


def test_bad_checksum_account_is_refused():
    try:
        v.account_to_pubkey(INFO["contents"]["account"][:-1] + "x")
    except ValueError:
        return
    raise AssertionError("checksum not enforced")
