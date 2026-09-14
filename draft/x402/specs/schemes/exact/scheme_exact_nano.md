# Scheme: `exact` on `Nano`

## Versions supported

- ❌ `v1`
- ✅ `v2`

## Supported Networks

- `nano:live` — Nano mainnet (production). Confirmation of a block on the Nano
  network is final ~1 second after broadcast; there is no sequencer, no bridge and
  no issuer.

> [!NOTE]
> **Scope.** This spec covers payments of the Nano network asset **XNO** from an
> agent-controlled Nano account to a resource server, following the **client-submitted
> (payment proof)** asset-transfer family of the `exact` scheme (see
> [scheme_exact.md](scheme_exact.md#client-submitted-payment-proof)). Nano has no
> smart contracts: there is no on-chain settlement *call* a facilitator can invoke.
> Settlement is binding an on-chain proof (a published block) to the request, after
> read-only verification on at least two independent RPC endpoints.
>
> A public Nano RPC (rpc.nano.to) is used for reads; reads are free and need no key.

## Summary

The `exact` scheme on Nano transfers an exact amount of XNO from the client to the
resource server. The server issues a **one-time Nano address per request** and returns
it as `payTo` in the payment requirements. The client signs a Nano *send* block locally,
broadcasts it (PoW via `work_generate`, publish via `process`), and presents the new block
hash as `paymentProof` in the `PaymentPayload`. The facilitator verifies, on at least two
independent RPC endpoints, that a confirmed block moves exactly `amount` XNO to `payTo`,
then binds the proof to the request exactly once.

The Nano address IS the memo: every payment relies on the public ledger, and a freshly
derived one-time address per request makes the proof self-binding to this request with no
trusted memo field and no facilitator chokepoint.

There is no fee, no gas and no sponsor. The facilitator does not relay or wrap a transaction:
the client's own send is the payment and its confirmation is the finality event.

## Payment flow

The flow is `upfront` (client-submitted payment proof): the payment is already on-chain
when the payload is presented, so no earlier ordering is available.

1. **Client** requests a protected resource from the **Resource Server**.
2. **Resource Server** responds with HTTP 402 and a `PaymentRequired` whose `accepts`
   array includes the Nano option (below).
3. **Client** derives/signs a Nano *send* of exactly `amount` to `payTo` using its own
   seed, obtains PoW for the frontier, and broadcasts it via a Nano RPC `process` action.
   It receives the new block hash.
4. **Client** sends a second request to the **Resource Server** carrying the
   `PaymentPayload` (below).
5. **Resource Server** forwards the payload and requirements to the **Facilitator's**
   `/verify` endpoint.
6. **Facilitator** reads `payTo`'s account history on **two independent RPC endpoints**,
   finds the confirmed block whose `hash` equals `payload.paymentProof`, and checks that it
   moves exactly `amount` XNO to `payTo`. It returns a `VerifyResponse`; verification is
   REQUIRED.
7. **Resource Server** calls the **Facilitator's** `/settle`. The facilitator re-runs full
   verification (never trusts the prior `/verify`), then **binds** the proof to this request
   — consuming `payload.paymentProof` for `request_id` exactly once — and returns
   `SettlementResponse`.
8. **Resource Server** executes the resource and returns the final response to the client.

## `PaymentRequirements` for `exact`

In addition to the standard x402 fields, Nano `exact` uses these `accepts[]` values:

```json
{
  "scheme": "exact",
  "network": "nano:live",
  "amount": "1000000000000000000000000000000",
  "asset": "XNO",
  "payTo": "nano_3p1zmep1qax1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f9",
  "maxTimeoutSeconds": 60,
  "extra": {
    "requestId": "req_9f2b6c"
  }
}
```

**Field Definitions:**

- `network`: MUST be `nano:live` (mainnet).
- `amount`: Required payment amount in **raw** units. Nano uses 30 decimal places, so
  `1 XNO = 10^30 raw`. The amount MUST be the exact raw integer expressed as a decimal
  string.
- `asset`: MUST be `XNO` (the native Nano asset). There is no token contract.
- `payTo`: The **one-time destination Nano address**. MUST be distinct per request and
  deterministic for a given `requestId` (see `extra.requestId`). The server holds the
  private key for this address and watches it on-chain; the address acts as the memo and
  as the request-binding instrument.
- `maxTimeoutSeconds`: Bounded validity window of the quote/address, e.g. `60`.
- `extra.requestId`: Opaque server-issued identifier that names this payment. The
  one-time `payTo` address is derived deterministically from a server master secret plus
  `requestId`, so the proof cannot be replayed against a different request (request
  binding).

## PaymentPayload `payload` Field

The payload contains the on-chain proof only; all other fields (payer address, amount,
destination) are derived by the facilitator from the verified block itself.

```json
{
  "paymentProof": "BA96F62D4EA651A21DA4282809F2541EA42481CA35018129F29B406EF3FE36C0"
}
```

Full `PaymentPayload` object:

```json
{
  "x402Version": 2,
  "resource": {
    "url": "https://api.example.com/premium-data",
    "description": "Access to premium market data",
    "mimeType": "application/json"
  },
  "accepted": {
    "scheme": "exact",
    "network": "nano:live",
    "amount": "1000000000000000000000000000000",
    "asset": "XNO",
    "payTo": "nano_1one_time_address_for_this_request...",
    "maxTimeoutSeconds": 60,
    "extra": {
      "requestId": "req_9f2b6c"
    }
  },
  "payload": {
    "paymentProof": "BA96F62D4EA651A21DA4282809F2541EA42481CA35018129F29B406EF3FE36C0"
  },
  "extensions": {}
}
```

**Field Definitions:**

- `paymentProof`: The 64-character uppercase hex block hash the client received from the
  Nano RPC `process` call. It MUST hash to a confirmed block on the Nano ledger.

## `SettlementResponse`

```json
{
  "success": true,
  "transaction": "BA96F62D4EA651A21DA4282809F2541EA42481CA35018129F29B406EF3FE36C0",
  "network": "nano:live",
  "payer": "nano_1some_client_account...",
  "amount": "1000000000000000000000000000000"
}
```

- `transaction`: The verified block hash (`payload.paymentProof`), byte-for-byte.
- `payer`: The Nano account that signed the send (derived from the confirmed block).
- `amount`: The amount that moved, in raw units.

## Facilitator Verification Rules (MUST)

A facilitator verifying `exact` on Nano MUST enforce all of the following before approving
a payment:

### 1. Protocol and requirement consistency

- `x402Version` MUST be `2`.
- `payload.accepted.scheme` and `requirements.scheme` MUST both equal `"exact"`.
- `payload.accepted.network` MUST equal `requirements.network` and MUST be `nano:live`.
- `payload.accepted.asset` MUST equal `requirements.asset` (`XNO`).
- `payload.accepted.payTo` MUST equal `requirements.payTo`.
- `payload.accepted.amount` MUST equal `requirements.amount` exactly.

### 2. Independent RPC confirmation (strategy law L1)

- The facilitator MUST read the account history of `payTo` on **at least two independent
  Nano RPC endpoints**.
- A payment MUST be refused if **any** of the required endpoints cannot confirm the block
  (a single-RPC operator outage MUST fail closed, never approve).
- `payload.paymentProof` MUST match a confirmed block `hash` present in `payTo`'s history
  on **both** endpoints.

### 3. Payment intent

- The confirmed block MUST be a `send` whose **receiver account equals `requirements.payTo`**.
- The `amount` moved by the block MUST equal `requirements.amount` **exactly**. Partial or
  overpayment MUST NOT be accepted as satisfying an `exact` requirement.
- The asset is implicitly XNO (the only Nano asset).

### 4. Finality and window

- The block MUST be **confirmed** (Nano confirms ~1 s after broadcast). The facilitator owns
  confirmation-depth policy; Nano's sub-second finality makes a single confirmed block the
  finality boundary.
- The payment MUST have landed within the `maxTimeoutSeconds` window of the requirements
  (an expired quote/address MUST be refused, matching the server's recorded expiry).

### 5. Replay / single-use claim

- A proof MUST be claimed **atomically** before the resource executes; of two concurrent
  presentations of the same `paymentProof` for the same `requestId`, exactly one MUST
  succeed.
- The canonical consumption key is `nano:live <block-hash>` joined to the request's
  `requestId`. The same `paymentProof` for a *different* `requestId` MUST be rejected by
  request binding (the one-time `payTo` per request makes this structurally impossible
  across requests).
- A consumed proof MUST be retained as long as it stays presentable; retry of a consumed
  proof MUST return a `spent`/duplicate error, never a second resource.

## Settlement Logic

1. Re-run every verification check (MUST NOT trust a prior `/verify` result).
2. Confirm the proof on both independent RPC endpoints as in section 2.
3. **Bind** the proof to this request: atomically claim the consumption key
   `nano:live <block-hash> <request_id>` exactly once. If already claimed, return
   `duplicate_settlement` / `spent` and do not deliver the resource.
4. Return `SettlementResponse` with `success: true`, `transaction` = the block hash,
   `payer` = the sending account, and `amount` = the exact raw amount.

## Failure disposition

Nano has no refund or clawback available to a facilitator (no smart contract, no issuer).
If the finality condition can no longer be met (e.g. the block never confirms or the proof
is not found on both endpoints) the payment is **not** returned to the payer by any
facilitator path. Clients MUST NOT assume a return path exists; they sign a send only when
they intend the payment.

## Duplicate Settlement Mitigation

The one-time `payTo` address plus request-bound proof make cross-request replay
structurally impossible. Within one request, the atomic single-use claim (section 5)
prevents the same proof from yielding two resources. Facilitators MUST hold the consumer
(typical SQLite `PRIMARY KEY` insert) across every process serving `/settle`, retaining each
key at least until the proof can no longer land (i.e. until `maxTimeoutSeconds` after the
window).

## Reference implementations

- Python reference (nano-mcp, an AI-agent built project): a self-custody Nano SDK that signs
  a local `send`, gets PoW via `rpc.nano.to` `work_generate`, and publishes via `process`;
  a pay-per-call service that derives a one-time HKDF address per `request_id`, watches that
  address's on-chain history, and approves exactly once (SQLite-backed atomic claim). The
  facilitator and the MCP `paidTool` wrapper implement the `/supported`, `/verify`, `/settle`
  surface described above.
- The mechanism implements the `SchemeNetworkClient`, `SchemeNetworkServer` and
  `SchemeNetworkFacilitator` interfaces in one SDK only; core packages are not modified.