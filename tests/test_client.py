"""Live-read tests against rpc.nano.to. Skipped if NANO_RPC_URL is unset."""
import os
import pytest

from nano_sdk import RpcClient

pytestmark = pytest.mark.network


@pytest.fixture(scope="session")
def client():
    return RpcClient()


@pytest.mark.skipif(not os.environ.get("NANO_RPC_URL"), reason="NANO_RPC_URL not set")
def test_version(client):
    v = client.version()
    assert v["network"] == "live"
    assert v["node_vendor"].startswith("Nano")


@pytest.mark.skipif(not os.environ.get("NANO_RPC_URL"), reason="NANO_RPC_URL not set")
def test_live_balance_read(client):
    b = client.account_balance("nano_1faucet7b6xjyha7m13objpn5ubkquzd6ska8kwopzf1ecbfmn35d1zey3ys")
    raw = b["balance"]
    assert raw.isdigit()
    assert int(raw) > 0
    assert "balance_nano" in b


@pytest.mark.skipif(not os.environ.get("NANO_RPC_URL"), reason="NANO_RPC_URL not set")
def test_live_history_read(client):
    h = client.account_history("nano_1faucet7b6xjyha7m13objpn5ubkquzd6ska8kwopzf1ecbfmn35d1zey3ys", count=5)
    assert len(h.get("history", [])) >= 1