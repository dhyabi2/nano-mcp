"""One-time payment address derivation for the nano-mcp pay-per-call server.

The invention (see .ledger/ranking.md): the service derives a *unique, one-time*
destination address per request_id from a server master key via HKDF-SHA256, and
returns {price_raw, address, request_id} in a quote. The agent sends exactly
price_raw there; the server watches that address's on-chain account_history and
approves the call only once the matching send is seen. The address IS the memo
(Nano blocks have no memo), and it is deterministic and reusable per request_id
only, so one payment authorizes exactly one call (replay-safe) with no trusted
verifier interposed and no off-chain settlement state.

Derivation:
    HKDF-SHA256(ikm=server_master_secret, salt=None, info=request_id, L=32)
        -> 32-byte Ed25519 private key  (RFC 5869)
    PublicKey = ed25519-blake2b(PrivK)          (nano_sdk.crypto.public_key)
    Address   = nano_ base32 encoding of PubK  (nano_sdk.crypto)
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from nano_sdk.crypto import Account, address_from_public_key, public_key

_HASH_LEN = hashlib.sha256().digest_size  # 32


def hkdf_sha256(
    ikm: bytes,
    salt: bytes | None = None,
    info: bytes = b"",
    length: int = 32,
) -> bytes:
    """RFC 5869 HKDF-SHA256. Used to turn the server master secret + request_id
    into a 32-byte Ed25519 private key."""
    # extract
    if salt is None:
        salt = b"\x00" * _HASH_LEN
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    # expand
    okm = b""
    t = b""
    counter = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def derive_one_time_account(master_secret: bytes, request_id: str) -> Account:
    """Return the one-time Nano account (private key, public key, address) for a
    request_id. Deterministic for the same (master_secret, request_id); distinct
    across request_ids."""
    if not isinstance(master_secret, bytes) or len(master_secret) < 16:
        raise ValueError("master_secret must be bytes of at least 16 bytes")
    priv = hkdf_sha256(ikm=master_secret, info=request_id.encode("utf-8"), length=32)
    pub = public_key(priv)
    return Account(private_key=priv, public_key=pub, address=address_from_public_key(pub))


def new_request_id() -> str:
    """A fresh random request_id (128 bits of entropy)."""
    return secrets.token_hex(16)
