"""verify_block_multi: believe a Nano block only when several independent public nodes return the SAME block.

Stdlib only, read-only: no key, no seed, no signing, no node of your own. For each node it asks
`block_info` (json_block true) for the hash, then
  1. recomputes the state-block hash from the returned contents (blake2b-256) and requires it to equal the hash
     you asked for - so a node cannot hand back different fields for the same hash;
  2. requires `confirmed` true;
  3. compares (subtype, account, destination, amount) across nodes.
PASS needs >= min_agree nodes (default 3) that all return one identical, confirmed, hash-true block and NO node
that contradicts it. A node that errors or says "not found" is listed as unreachable/missing, never as agreement
and never as a contradiction. Any contradiction FAILS, listing both sides: it does not break ties.
What it does not do: check the ed25519 signature (needs a crypto dep) or prove the nodes are not run by one party;
the node set is yours to choose (`nodes=`), and the list used is returned in the result.

  python3 nano_mcp/verify_multi.py HASH  # stdlib only, runs without installing [--node URL]... [--min-agree 3] [--payee nano_..] [--amount-raw N]
Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request

DEFAULT_NODES = (
    "https://rpc.nano.to",
    "https://node.somenano.com/proxy",
    "https://rainstorm.city/api",
    "https://nanoslo.0x.no/proxy",
)
_HEX64 = re.compile(r"[0-9A-Fa-f]{64}")
_ALPHA = "13456789abcdefghijkmnopqrstuwxyz"


def account_to_pubkey(addr: str) -> bytes:
    """nano_/xrb_ address -> 32-byte public key; ValueError if malformed or the checksum is wrong."""
    m = re.fullmatch(r"(?:nano|xrb)_([13][%s]{51})([%s]{8})" % (_ALPHA, _ALPHA), addr or "")
    if not m:
        raise ValueError("not a nano account")
    n = 0
    for c in m.group(1):
        n = (n << 5) | _ALPHA.index(c)
    key = (n & ((1 << 256) - 1)).to_bytes(32, "big")
    chk = 0
    for c in m.group(2):
        chk = (chk << 5) | _ALPHA.index(c)
    if hashlib.blake2b(key, digest_size=5).digest()[::-1] != chk.to_bytes(5, "big"):
        raise ValueError("bad account checksum")
    return key


def state_block_hash(c: dict) -> str:
    h = hashlib.blake2b(digest_size=32)
    h.update((6).to_bytes(32, "big"))
    h.update(account_to_pubkey(c["account"]))
    h.update(bytes.fromhex(c["previous"]))
    h.update(account_to_pubkey(c["representative"]))
    h.update(int(c["balance"]).to_bytes(16, "big"))
    h.update(bytes.fromhex(c["link"]))
    return h.hexdigest().upper()


def _post(url: str, body: dict, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "nano-mcp-verify-multi"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(1_000_000))


def read_one(url: str, block_hash: str, fetch=None) -> dict:
    """One node's reading: {'node', 'status': ok|missing|error|unconfirmed|lied, 'block': {...}|None, 'why'}."""
    try:
        info = (fetch or _post)(url, {"action": "block_info", "json_block": "true", "hash": block_hash})
    except Exception as e:  # network, TLS, JSON: this node says nothing
        return {"node": url, "status": "error", "block": None, "why": type(e).__name__}
    if not isinstance(info, dict) or "error" in info:
        return {"node": url, "status": "missing", "block": None, "why": str((info or {}).get("error", "bad reply"))[:80]}
    c = info.get("contents")
    try:
        if not isinstance(c, dict) or c.get("type") != "state":
            raise ValueError("contents not a state block object")
        if state_block_hash(c) != block_hash.upper():
            return {"node": url, "status": "lied", "block": None, "why": "contents do not hash to the requested block"}
        blk = {"subtype": info.get("subtype"), "account": c["account"], "destination": c.get("link_as_account"),
               "amount": str(info.get("amount")), "link": c["link"]}
    except (KeyError, ValueError, TypeError) as e:
        return {"node": url, "status": "error", "block": None, "why": "unreadable: %s" % e}
    if str(info.get("confirmed")).lower() != "true":
        return {"node": url, "status": "unconfirmed", "block": blk, "why": "not confirmed"}
    return {"node": url, "status": "ok", "block": blk, "why": ""}


def verify_block_multi(block_hash: str, nodes=DEFAULT_NODES, min_agree: int = 3, payee: str | None = None,
                       amount_raw: str | None = None, fetch=None) -> dict:
    if not isinstance(block_hash, str) or not _HEX64.fullmatch(block_hash):
        return {"verdict": "fail", "why": "block hash is not 64 hex characters; no node was asked", "nodes": []}
    reads = [read_one(u, block_hash, fetch) for u in nodes]
    ok = [r for r in reads if r["status"] == "ok"]
    out = {"verdict": "fail", "block_hash": block_hash.upper(), "min_agree": min_agree, "nodes": reads,
           "agreeing_nodes": [r["node"] for r in ok], "block": None}
    liars = [r["node"] for r in reads if r["status"] == "lied"]
    if liars:
        out["why"] = "node(s) returned contents that do not hash to the block: %s" % ", ".join(liars)
        return out
    distinct = {json.dumps(r["block"], sort_keys=True) for r in reads if r["block"]}
    if len(distinct) > 1:
        out["why"] = "nodes contradict each other about this block; no tie is broken"
        return out
    if len(ok) < min_agree:
        out["why"] = "only %d of the required %d nodes returned the confirmed block" % (len(ok), min_agree)
        return out
    blk = ok[0]["block"]
    if payee and blk["destination"] != payee:
        out["why"] = "block pays %s, not the expected payee" % blk["destination"]
        out["block"] = blk
        return out
    if amount_raw is not None and blk["amount"] != str(amount_raw):
        out["why"] = "block amount %s is not the expected %s" % (blk["amount"], amount_raw)
        out["block"] = blk
        return out
    out.update(verdict="pass", block=blk, why="%d independent nodes returned one identical confirmed block" % len(ok))
    return out


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("block_hash")
    p.add_argument("--node", action="append")
    p.add_argument("--min-agree", type=int, default=3)
    p.add_argument("--payee")
    p.add_argument("--amount-raw")
    a = p.parse_args(argv)
    r = verify_block_multi(a.block_hash, tuple(a.node) if a.node else DEFAULT_NODES, a.min_agree, a.payee, a.amount_raw)
    print(json.dumps(r, indent=1))
    return 0 if r["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
