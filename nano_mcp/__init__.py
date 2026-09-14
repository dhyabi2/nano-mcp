"""nano-mcp server package: pay-per-call tools with one-time payment addresses.

Usage (agent): server.quote(price_nano) -> one-time address; SDK wallet.send there;
then server.verify_payment(request_id, amount_raw) approves exactly once.
"""
from .oneshot import derive_one_time_account, hkdf_sha256, new_request_id
from .service import PaymentService, Quote
from .store import ApprovalStore

__all__ = [
    "ApprovalStore",
    "PaymentService",
    "Quote",
    "derive_one_time_account",
    "hkdf_sha256",
    "new_request_id",
]

__version__ = "0.1.0"
