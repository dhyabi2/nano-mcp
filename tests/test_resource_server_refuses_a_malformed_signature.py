"""A malformed `payment-signature` is refused with a reason, not a dropped connection.

`ResourceApp.complete()` read the presented payload with `.get` straight away:

    accepted = payload.get("accepted") or {}
    request_id = str((accepted.get("extra") or {}).get("requestId") or "")

The payload is a stranger's bytes - a base64 header decoded by `b64decode_json`,
which happily returns a list, a string or a number, because those are valid JSON
too. Each of those raised `AttributeError` out of `complete()`, and in the HTTP
adapter that escaped `do_GET`, so `ThreadingHTTPServer` closed the socket with
**no status line at all** and printed a traceback per request. Measured against
the real handler before the fix, every one of these got
`RemoteProtocolError: Server disconnected without sending a response`:

    [1]                                   payload is an array
    "x"                                   payload is a string
    5                                     payload is a number
    {"accepted": [1], ...}                accepted is an array
    {"accepted": {"extra": [1]}, ...}     extra is an array

A buyer cannot tell its own bad payload from a seller that is down, so the
sensible client behaviour - retry the disconnect - is the wrong one, and the
seller serves nothing while printing a stack trace for each attempt. The
facilitator's `/verify` and `/settle` were fixed this way earlier
(`tests/test_facilitator_reads_the_proof_safely.py`); this is the resource-server
half of the same handshake.

Each refusal keeps the shape `complete()` already returns for a payload it will
not accept, so the HTTP adapter answers **402 with the reason** and the protected
resource is never produced.
"""

import base64
import json
import os
import sys
import threading

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_httpx402 import AMOUNT_RAW, _build_stack  # noqa: E402

MALFORMED = [
    pytest.param([1], "payload must be a JSON object", id="payload-is-an-array"),
    pytest.param("x", "payload must be a JSON object", id="payload-is-a-string"),
    pytest.param(5, "payload must be a JSON object", id="payload-is-a-number"),
    pytest.param(None, "payload must be a JSON object", id="payload-is-null"),
    pytest.param(True, "payload must be a JSON object", id="payload-is-a-boolean"),
    pytest.param(
        {"x402Version": 2, "accepted": [1], "payload": {"paymentProof": "A" * 64}},
        "payload.accepted must be a JSON object",
        id="accepted-is-an-array",
    ),
    pytest.param(
        {"x402Version": 2, "accepted": "nano_x", "payload": {"paymentProof": "A" * 64}},
        "payload.accepted must be a JSON object",
        id="accepted-is-a-string",
    ),
    pytest.param(
        {"x402Version": 2, "accepted": {"extra": [1]}, "payload": {}},
        "payload.accepted.extra must be a JSON object",
        id="extra-is-an-array",
    ),
    pytest.param(
        {"x402Version": 2, "accepted": {"extra": "r1"}, "payload": {}},
        "payload.accepted.extra must be a JSON object",
        id="extra-is-a-string",
    ),
]


@pytest.fixture
def served():
    app, store_a, store_b, httpd = _build_stack()
    threading.current_thread()  # the server thread is started by _build_stack
    client = httpx.Client(base_url=f"http://127.0.0.1:{httpd.server_address[1]}")
    try:
        yield app, client
    finally:
        client.close()
        httpd.shutdown()
        httpd.server_close()


def _header(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


@pytest.mark.parametrize("payload,message", MALFORMED)
def test_complete_refuses_instead_of_raising(payload, message):
    app, _client = _app()
    result = app.complete(payload)
    assert result["ok"] is False
    assert result["invalid"] is True
    assert result["error_reason"] == "invalid"
    assert result["error_message"] == message


@pytest.mark.parametrize("payload,message", MALFORMED)
def test_over_http_the_seller_answers_402_with_the_reason(served, payload, message):
    _app_, client = served
    response = client.get("/", headers={"payment-signature": _header(payload)})
    assert response.status_code == 402
    body = response.json()
    assert body["message"] == message
    assert "data" not in body, "the protected resource must never be produced"


def test_a_signature_that_is_not_base64_json_is_still_a_400(served):
    _app_, client = served
    response = client.get("/", headers={"payment-signature": "!!! not base64 !!!"})
    assert response.status_code == 400


def test_an_unpaid_request_still_gets_its_402_challenge(served):
    """The control: the handshake itself is untouched by the guards."""
    _app_, client = served
    response = client.get("/")
    assert response.status_code == 402
    accepts = response.json()["accepts"]
    assert accepts[0]["amount"] == AMOUNT_RAW
    assert accepts[0]["payTo"].startswith("nano_")
    assert accepts[0]["extra"]["requestId"]


def test_a_well_formed_payload_for_an_unknown_request_still_reads_as_a_mismatch(served):
    """Also the control: a payload that IS an object keeps its old refusal, which
    is about the requirements, not about the shape."""
    app, _client = served
    result = app.complete({
        "x402Version": 2,
        "accepted": {"scheme": "exact", "network": "nano:live", "asset": "XNO",
                     "amount": AMOUNT_RAW, "payTo": "nano_1" + "1" * 59,
                     "extra": {"requestId": "req-nobody-issued"}},
        "payload": {"paymentProof": "A" * 64},
    })
    assert result["ok"] is False
    assert "does not match the requirements issued for this request" in result["error_message"]


def _app():
    app, _a, _b, httpd = _build_stack()
    httpd.shutdown()
    httpd.server_close()
    return app, None
