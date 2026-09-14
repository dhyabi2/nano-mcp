"""Nano state-block construction and signing, per docs.nano.org.

State block (v15+ only block type). The bytes hashed for both the block hash and
the signature are, in order (all binary, no ASCII):

    1. block preamble (32 bytes, value 0x06)
    2. account      (32 bytes, public key)
    3. previous     (32 bytes, frontier hash; 0 for the first/open block)
    4. representative (32 bytes, public key)
    5. balance      (16 bytes, big-endian raw balance AFTER this transaction)
    6. link         (32 bytes: destination public key for a send, or the paired
                     send block hash for a receive)

The block hash is blake2b-256 of those bytes. The signature is Ed25519-Blake2b
over the same digest. Verified against the docs.nano.org "creating transactions"
examples (send / receive / first-receive), whose expected hashes and signatures
are encoded as unit-test vectors.
"""
from __future__ import annotations

import hashlib
import re

import ed25519_blake2b

from .crypto import public_key_from_address

STATE_PREAMBLE = 0x06  # 32-byte field, value 6
_HASH_LENGTH = 32
_HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")


def _block_bytes(
    account_pub: bytes,
    previous: bytes,
    representative_pub: bytes,
    balance_raw: int,
    link: bytes,
) -> bytes:
    """The exact byte string that is blake2b-256 hashed for a state block."""
    if len(account_pub) != 32 or len(previous) != 32:
        raise ValueError("account/previous must be 32 bytes")
    if len(representative_pub) != 32 or len(link) != 32:
        raise ValueError("representative/link must be 32 bytes")
    if not (0 <= balance_raw < (1 << 128)):
        raise ValueError("balance must fit in 128 bits")
    return (
        STATE_PREAMBLE.to_bytes(32, "big")
        + account_pub
        + previous
        + representative_pub
        + balance_raw.to_bytes(16, "big")
        + link
    )


def block_hash(
    account_pub: bytes,
    previous: bytes,
    representative_pub: bytes,
    balance_raw: int,
    link: bytes,
) -> bytes:
    """blake2b-256 digest of the state-block byte string (the block hash)."""
    return hashlib.blake2b(
        _block_bytes(account_pub, previous, representative_pub, balance_raw, link),
        digest_size=_HASH_LENGTH,
    ).digest()


def sign(private_key: bytes, message: bytes) -> bytes:
    """Ed25519-Blake2b signature over `message` (the block-hash digest)."""
    return ed25519_blake2b.SigningKey(private_key).sign(message)


def build_send_block(
    private_key: bytes,
    account_pub: bytes,
    account_address: str,
    previous: bytes,
    representative_address: str,
    new_balance_raw: int,
    destination_address: str,
    work: str,
) -> dict:
    """Return a signed Nano `state` send block dict ready for the `process` RPC.

    The `link` field is the destination address's public key (hex). `work` is the
    proof-of-work hex string for the block (generated separately via work_generate
    over `previous`).
    """
    if len(previous) != 32:
        raise ValueError("previous must be 32 bytes")
    if len(private_key) != 32:
        raise ValueError("private_key must be 32 bytes")

    dest_pub = public_key_from_address(destination_address)
    rep_pub = public_key_from_address(representative_address)
    digest = block_hash(account_pub, previous, rep_pub, new_balance_raw, dest_pub)
    signature = sign(private_key, digest)

    return {
        "type": "state",
        "account": account_address,
        "previous": previous.hex().upper(),
        "representative": representative_address,
        "balance": str(new_balance_raw),
        "link": dest_pub.hex().upper(),
        "link_as_account": destination_address,
        "signature": signature.hex().upper(),
        "work": work,
    }


def build_receive_block(
    private_key: bytes,
    account_pub: bytes,
    account_address: str,
    previous: bytes,
    representative_address: str,
    new_balance_raw: int,
    source_block_hash: str,
    work: str,
) -> dict:
    """Return a signed Nano `state` receive block dict ready for `process`.

    A receive claims a pending send: the `link` field is the 64-hex hash of the
    send block being received (not a destination address). `previous` is the
    account's current frontier (all-zeros for the first/open block). `work` is
    the proof-of-work hex for the block (generated over `previous`).
    """
    if len(previous) != 32:
        raise ValueError("previous must be 32 bytes")
    if len(private_key) != 32:
        raise ValueError("private_key must be 32 bytes")
    if not _HEX64.match(source_block_hash):
        raise ValueError("source_block_hash must be a 64-hex block hash")

    rep_pub = public_key_from_address(representative_address)
    link = bytes.fromhex(source_block_hash)
    digest = block_hash(account_pub, previous, rep_pub, new_balance_raw, link)
    signature = sign(private_key, digest)

    return {
        "type": "state",
        "account": account_address,
        "previous": previous.hex().upper(),
        "representative": representative_address,
        "balance": str(new_balance_raw),
        "link": source_block_hash.upper(),
        "signature": signature.hex().upper(),
        "work": work,
    }
