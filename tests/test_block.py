"""State-block construction + signing.

Anchored on verifiable truth rather than docs narrative:

1. The live-chain ground truth: the SDK recomputes the exact hash of real,
   confirmed blocks pulled from rpc.nano.to block_info (network test).
2. The docs.nano.org *receive* example, which is internally self-consistent:
   our hash + signature reproduce its documented hash + signature byte-for-byte.
3. Signature self-verification: an Ed25519-Blake2b signature we make over a block
   hash verifies against the account public key (proves it is valid for the
   network to accept).

The docs *send* and *first-receive* block_create examples are not used as exact
field-level vectors: the docs make them from a single synthetic account_info
("pretend the previous example was not broadcast") and the narrative fields they
print do not correspond to the hash they print. The live-chain test is the
authoritative hash check.
"""
import os

import ed25519_blake2b
import pytest

from nano_sdk import public_key_from_address
from nano_sdk.block import block_hash, build_send_block, sign

REP = "nano_1stofnrxuz3cai7ze75o174bpm7scwj9jn3nxsn8ntzg784jf1gzn1jjdkou"
DOCS_PUB = "3068BB1CA04525BB0E416C485FE6A67FD52540227D267CC8B6E8DA958A7FA039"
DOCS_PRIV = "781186FB9EF17DB6E3D1056550D9FAE5D5BBADA6A6BC370E4CBB938B1DC71DA3"
DOCS_ADDR = "nano_1e5aqegc1jb7qe964u4adzmcezyo6o146zb8hm6dft8tkp79za3sxwjym5rx"


def _verify(pub: bytes, sig: bytes, msg: bytes) -> bool:
    try:
        ed25519_blake2b.VerifyingKey(pub).verify(sig, msg)
        return True
    except Exception:
        return False


def test_receive_vector_matches_docs_exactly():
    """The self-consistent docs receive example must reproduce byte-for-byte."""
    priv = bytes.fromhex(DOCS_PRIV)
    account_pub = bytes.fromhex(DOCS_PUB)
    previous = bytes.fromhex("92BA74A7D6DC7557F3EDA95ADC6341D51AC777A0A6FF0688A5C492AB2B2CB40D")
    new_balance = 11618869000000000000000000000000
    link = bytes.fromhex("CBC911F57B6827649423C92C88C0C56637A4274FF019E77E24D61D12B5338783")
    expected_hash = "350D145570578A36D3D5ADE58DC7465F4CAAF257DD55BD93055FF826057E2CDD"
    expected_sig = (
        "EEFFE1EFCCC8F2F6F2F1B79B80ABE855939DD9D6341323186494ADEE775DAADB3"
        "B6A6A07A85511F2185F6E739C4A54F1454436E22255A542ED879FD04FEED001"
    )
    rep_pub = public_key_from_address(REP)
    h = block_hash(account_pub, previous, rep_pub, new_balance, link)
    assert h.hex().upper() == expected_hash
    assert sign(priv, h).hex().upper() == expected_sig


def test_send_block_constructs_and_signature_is_valid():
    """Build a send block; the signature must verify over the block hash with the
    account's public key (exactly what the network checks)."""
    priv = bytes.fromhex(DOCS_PRIV)
    account_pub = bytes.fromhex(DOCS_PUB)
    previous = bytes.fromhex("92BA74A7D6DC7557F3EDA95ADC6341D51AC777A0A6FF0688A5C492AB2B2CB40D")
    new_balance = 3618869000000000000000000000000
    dest = "nano_1q3hqecaw15cjt7thbtxu3pbzr1eihtzzpzxguoc37bj1wc5ffoh7w74gi6p"
    dest_pub = public_key_from_address(dest)
    rep_pub = public_key_from_address(REP)

    blk = build_send_block(
        private_key=priv,
        account_pub=account_pub,
        account_address=DOCS_ADDR,
        previous=previous,
        representative_address=REP,
        new_balance_raw=new_balance,
        destination_address=dest,
        work="fbffed7c73b61367",
    )
    # fields are populated correctly
    assert blk["type"] == "state"
    assert blk["balance"] == str(new_balance)
    assert blk["link"] == dest_pub.hex().upper()
    assert blk["link_as_account"] == dest
    assert blk["previous"] == previous.hex().upper()
    assert len(bytes.fromhex(blk["signature"])) == 64

    # signature verifies over the block hash with the account's public key
    h = block_hash(account_pub, previous, rep_pub, new_balance, dest_pub)
    sig = bytes.fromhex(blk["signature"])
    assert _verify(account_pub, sig, h), "signature must verify over block hash"


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("NANO_RPC_URL"), reason="NANO_RPC_URL not set")
def test_live_confirmed_block_hash_recomputed():
    """The SDK must recompute the exact hash of real, confirmed on-chain blocks."""
    from nano_sdk import RpcClient

    client = RpcClient()
    checked = 0
    for address in (
        "nano_1faucet7b6xjyha7m13objpn5ubkquzd6ska8kwopzf1ecbfmn35d1zey3ys",
        "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3",
    ):
        hist = client.account_history(address, count=2)
        for entry in hist.get("history", []):
            real_hash = entry["hash"]
            info = client.block_info(real_hash)
            b = info.get("contents") or info
            acct_pub = public_key_from_address(b["account"])
            rep_pub = public_key_from_address(b["representative"])
            prev = bytes.fromhex(b["previous"])
            link = bytes.fromhex(b["link"])
            bal = int(b["balance"])
            recomputed = block_hash(acct_pub, prev, rep_pub, bal, link)
            assert recomputed.hex().upper() == real_hash, (
                f"hash mismatch for block {real_hash}"
            )
            checked += 1
        break  # first account is enough; two blocks each
    assert checked >= 1