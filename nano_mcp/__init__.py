"""nano-mcp server package: pay-per-call tools with one-time payment addresses.

Usage (agent): server.quote(price_nano) -> one-time address; SDK wallet.send there;
then server.verify_payment(request_id, amount_raw) approves exactly once.
"""
from .evidence import append_nano_tx, own_accounts_from_env, should_log
from .oneshot import derive_one_time_account, hkdf_sha256, new_request_id
from .pricing import (
    DEFAULT_SOURCES,
    QUOTE_TTL_SECONDS,
    exact_xno_amount,
    fetch_median_xno_usd,
    median,
    usd_to_xno_raw,
)
from .scorecard import (
    JournalProto,
    build as scorecard_build,
    count_external_receipts,
    make_manifest,
    verify as scorecard_verify,
)
from .service import PaymentService, Quote
from .store import ApprovalStore

__all__ = [
    "ApprovalStore",
    "DEFAULT_SOURCES",
    "JournalProto",
    "PaymentService",
    "QUOTE_TTL_SECONDS",
    "Quote",
    "append_nano_tx",
    "count_external_receipts",
    "derive_one_time_account",
    "exact_xno_amount",
    "fetch_median_xno_usd",
    "hkdf_sha256",
    "make_manifest",
    "median",
    "new_request_id",
    "own_accounts_from_env",
    "scorecard_build",
    "scorecard_verify",
    "should_log",
    "usd_to_xno_raw",
]

__version__ = "0.1.0"
