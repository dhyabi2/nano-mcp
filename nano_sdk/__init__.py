"""nano-mcp SDK: hold XNO and pay per API call in Nano, via rpc.nano.to."""
from .client import RpcClient, RpcError
from .crypto import (
    Account,
    address_from_public_key,
    derive_account,
    derive_private_key,
    public_key,
    public_key_from_address,
    validate_address,
)
from .units import nano_str, nano_to_raw, raw_to_nano
from .buyer import (
    DailyCapExceeded as BuyerDailyCapExceeded,
    ExpiredMandate,
    Mandate,
    MandateError,
    SessionCapExceeded,
    SessionWallet,
    derive_session_account,
    issue_mandate,
    verify_mandate,
)
from .wallet import (
    DailyCapExceeded,
    InsufficientBalance,
    RpcBalanceError,
    Wallet,
    DEFAULT_DAILY_CAP_RAW,
)

__all__ = [
    "Account",
    "BuyerDailyCapExceeded",
    "DailyCapExceeded",
    "DEFAULT_DAILY_CAP_RAW",
    "ExpiredMandate",
    "InsufficientBalance",
    "Mandate",
    "MandateError",
    "RpcBalanceError",
    "RpcClient",
    "RpcError",
    "SessionCapExceeded",
    "SessionWallet",
    "Wallet",
    "address_from_public_key",
    "derive_account",
    "derive_private_key",
    "derive_session_account",
    "issue_mandate",
    "nano_str",
    "nano_to_raw",
    "public_key",
    "public_key_from_address",
    "raw_to_nano",
    "validate_address",
    "verify_mandate",
]

__version__ = "0.1.0"