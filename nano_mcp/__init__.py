"""nano-mcp server package: pay-per-call tools with one-time payment addresses.

Usage (agent): server.quote(price_nano) -> one-time address; SDK wallet.send there;
then server.verify_payment(request_id, amount_raw) approves exactly once.
"""
from .evidence import append_nano_tx, own_accounts_from_env, should_log
from .facilitator import (
    ClaimStore as FacilitatorClaimStore,
    Facilitator,
    FacilitatorConfig,
    RpcEndpoint,
    RpcError as FacilitatorRpcError,
    VerificationResult,
    consumption_key,
    make_handler,
    parse_raw as facilitator_parse_raw,
    serve as facilitator_serve,
    verify_block_on_independent_endpoints,
)
from .httpx402 import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_RESPONSE_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    ResourceApp,
    b64decode_json,
    b64encode_json,
    build_payment_payload,
    derive_requirements,
    make_resource_handler,
    pay_and_fetch,
    payment_required_obj,
    serve_resource,
)
from .oneshot import derive_one_time_account, hkdf_sha256, new_request_id
from .paidtool import PaidToolServer, build_paid_server
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
    "Facilitator",
    "FacilitatorClaimStore",
    "FacilitatorConfig",
    "FacilitatorRpcError",
    "JournalProto",
    "PAYMENT_REQUIRED_HEADER",
    "PAYMENT_RESPONSE_HEADER",
    "PAYMENT_SIGNATURE_HEADER",
    "PaymentService",
    "PaidToolServer",
    "QUOTE_TTL_SECONDS",
    "Quote",
    "ResourceApp",
    "RpcEndpoint",
    "VerificationResult",
    "append_nano_tx",
    "b64decode_json",
    "b64encode_json",
    "build_paid_server",
    "build_payment_payload",
    "consumption_key",
    "count_external_receipts",
    "derive_one_time_account",
    "derive_requirements",
    "exact_xno_amount",
    "facilitator_parse_raw",
    "facilitator_serve",
    "fetch_median_xno_usd",
    "hkdf_sha256",
    "make_handler",
    "make_manifest",
    "make_resource_handler",
    "median",
    "new_request_id",
    "own_accounts_from_env",
    "pay_and_fetch",
    "payment_required_obj",
    "scorecard_build",
    "scorecard_verify",
    "serve_resource",
    "should_log",
    "usd_to_xno_raw",
    "verify_block_on_independent_endpoints",
]

__version__ = "0.1.0"
