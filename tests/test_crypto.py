"""Crypto/units tests. Address vectors verified against the live rpc.nano.to account_key RPC."""
import hashlib

import pytest

from nano_sdk import (
    address_from_public_key,
    derive_account,
    derive_private_key,
    nano_str,
    nano_to_raw,
    public_key,
    public_key_from_address,
    raw_to_nano,
    validate_address,
)

# (public_key_hex, nano_address) ground truth from rpc.nano.to account_key
NODE_PAIRS = [
    (
        "351B53345493B1F3D05980354C6D41ED32BEFEB2664834B95B7DA06292D9D023",
        "nano_1faucet7b6xjyha7m13objpn5ubkquzd6ska8kwopzf1ecbfmn35d1zey3ys",
    ),
    (
        "E89208DD038FBB269987689621D52292AE9C35941A7484756ECCED92A65093BA",
        "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3",
    ),
    (
        "00" * 32,
        "nano_1111111111111111111111111111111111111111111111111111hifc8npp",
    ),
]

# docs.nano.org/integration-guides/the-basics canonical derivation vector
DOCS_SEED = "0000000000000000000000000000000000000000000000000000000000000001"
DOCS_PRIV = "1495F2D49159CC2EAAAA97EBB42346418E1268AFF16D7FCA90E6BAD6D0965520"


def test_private_key_derivation_matches_official_vector():
    priv = derive_private_key(DOCS_SEED, index=1)
    assert priv.hex().upper() == DOCS_PRIV


@pytest.mark.parametrize("pub_hex,addr", NODE_PAIRS)
def test_address_encoding_matches_node(pub_hex, addr):
    assert address_from_public_key(bytes.fromhex(pub_hex)) == addr


@pytest.mark.parametrize("pub_hex,addr", NODE_PAIRS)
def test_address_decoding_and_checksum(pub_hex, addr):
    pub = public_key_from_address(addr)
    assert pub.hex().upper() == pub_hex
    assert validate_address(addr)


def test_validate_rejects_bad_checksum():
    good = NODE_PAIRS[0][1]
    tampered = good[:-1] + ("1" if good[-1] != "1" else "3")
    assert validate_address(tampered) is False


def test_validate_rejects_garbage():
    assert validate_address("nano_zzzz") is False
    assert validate_address("bitcoin1q..." ) is False


def test_derive_is_deterministic_and_index_unique():
    a1 = derive_account(DOCS_SEED, index=0)
    a2 = derive_account(DOCS_SEED, index=0)
    a3 = derive_account(DOCS_SEED, index=1)
    assert a1 == a2
    assert a1.address == a2.address
    assert a1.address != a3.address
    assert a1.private_key != a3.private_key
    # private key never leaks in repr
    assert a1.private_key.hex() not in repr(a1)


def test_public_key_derivation_consistent():
    a = derive_account(DOCS_SEED, index=0)
    assert public_key(a.private_key) == a.public_key


def test_units_roundtrip():
    assert nano_to_raw("1") == 10**30
    assert nano_to_raw("0.000001") == 10**24
    assert raw_to_nano(10**24) * 10**30 == 10**24
    assert nano_str(10**24) == "0.000001"


def test_units_reject_overflow_precision():
    with pytest.raises(ValueError):
        nano_to_raw("0." + "0" * 29 + "123456")  # more than 30 decimals