"""Receive the owner's test funding into the treasury (stage gate 1, step 1).

The treasury has no frontier yet (open block), so account_info returns
"Account not found". We handle that: balance=0, frontier=all-zeros, then build
and broadcast a receive block for the pending send. Read-only until the final
process call. Prints the receive block hash and the new balance.
"""
import os
import sys

sys.path.insert(0, "/root/nano-agent/nano-mcp")

from nano_sdk import RpcClient, Wallet
from nano_sdk.crypto import derive_account

SEED = os.environ["NANO_AGENT_SEED"]
ACCOUNT = os.environ["NANO_AGENT_ACCOUNT"]
PENDING_HASH = "B42D35136339688A1E1AA8A5E07F5C95C15A7E806D2EE803D293B3BEE52010FB"


class OpenBlockClient(RpcClient):
    """RpcClient that treats 'Account not found' as a fresh (open) account."""

    def account_info(self, account: str) -> dict:
        try:
            return super().account_info(account)
        except Exception as e:
            if "Account not found" in str(e):
                return {"balance": "0", "frontier": "0" * 64, "representative": ""}
            raise


def main() -> None:
    client = OpenBlockClient()
    acct = derive_account(SEED, 0)
    assert acct.address == ACCOUNT, f"derived {acct.address} != treasury {ACCOUNT}"

    # Confirm the pending block exists and its amount.
    src = client.block_info(PENDING_HASH)
    amount_raw = int(src.get("amount", "0"))
    print(f"pending source: {PENDING_HASH}")
    print(f"pending amount: {amount_raw} raw = {amount_raw / 10**30} XNO")

    w = Wallet(seed=SEED, client=client)
    h, blk = w.receive(PENDING_HASH, index=0)
    print(f"receive block hash: {h}")
    print(f"receive block: {blk}")

    # Verify on-chain.
    info = client.account_info(ACCOUNT)
    print(f"new account_info: {info}")


if __name__ == "__main__":
    main()
