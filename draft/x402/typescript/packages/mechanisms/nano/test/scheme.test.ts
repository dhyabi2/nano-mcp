/**
 * Offline tests for the x402 `exact`-on-`nano` mechanism draft.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 * No real network, no real chain contact, no funds moved: these exercise the
 * deterministic primitives (one-time address, raw conversion), the client
 * payload builder, the atomic claim store, and the requirement checks that run
 * without a chain.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ExactNanoClient, ExactNanoServer, ExactNanoFacilitator } from "../src/index.js";
import { RecordingPayer } from "../src/exact/client/payer.js";
import type { NanoFacilitatorConfig } from "../src/exact/facilitator/index.js";
import { InMemoryClaimStore, consumptionKey } from "../src/claim.js";
import {
    defaultSeedToPublicKey,
    deriveAccountKey,
    deriveOneTimeAddress,
    generateMasterSeed,
    nanoAddress,
} from "../src/crypto.js";
import { NANO_ASSET, NANO_LIVE_NETWORK } from "../src/types.js";
import type { PaymentRequirements } from "@x402/core/types";

const MASTER = new Uint8Array(32).fill(7);

const reqs: PaymentRequirements = {
  scheme: "exact",
  network: NANO_LIVE_NETWORK,
  asset: NANO_ASSET,
  amount: "1000000000000000000000000000000",
  payTo: "nano_3p1zmep1qax1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f9",
  maxTimeoutSeconds: 60,
  extra: { requestId: "req_abc" },
};

test("one-time address is a nano_ address, deterministic, distinct per requestId", () => {
    const a1 = deriveOneTimeAddress(MASTER, "req_1");
    const a1b = deriveOneTimeAddress(MASTER, "req_1");
    const a2 = deriveOneTimeAddress(MASTER, "req_2");
    assert.match(a1, /^nano_[13456789abcdefghijkmnopqrstuwxyz]{60}$/);
    assert.equal(a1, a1b);
    assert.notEqual(a1, a2);
});

test("one-time address is the pubkey of the derived account key (server can receive on it)", () => {
  const priv = deriveAccountKey(MASTER, "req_x");
  const pub = defaultSeedToPublicKey(priv);
  const pubFromSeed = defaultSeedToPublicKey(deriveAccountKey(MASTER, "req_x")); // deterministic
  assert.deepEqual(pub, pubFromSeed);
  assert.equal(nanoAddress(pub), deriveOneTimeAddress(MASTER, "req_x"));
});

test("server enhancePaymentRequirements sets nano:live / XNO / one-time payTo", async () => {
  const server = new ExactNanoServer({ masterSeed: MASTER });
  const out = await server.enhancePaymentRequirements(reqs, { x402Version: 2, scheme: "exact", network: NANO_LIVE_NETWORK }, []);
  assert.equal(out.network, NANO_LIVE_NETWORK);
  assert.equal(out.asset, NANO_ASSET);
  assert.match(out.payTo, /^nano_/);
  assert.equal(out.payTo, deriveOneTimeAddress(MASTER, "req_abc"));
});

test("server parsePrice converts decimal XNO to exact raw (30 decimals)", async () => {
  const server = new ExactNanoServer({ masterSeed: MASTER });
  const parsed = await server.parsePrice("1.5", NANO_LIVE_NETWORK);
  assert.equal(parsed.asset, NANO_ASSET);
  assert.equal(parsed.amount, "1500000000000000000000000000000");
});

test("client creates a 64-hex paymentProof from the payer", async () => {
  const payer = new RecordingPayer((_to, _amt) => "BA96F62D4EA651A21DA4282809F2541EA42481CA35018129F29B406EF3FE36C0");
  const client = new ExactNanoClient(payer);
  const result = await client.createPaymentPayload(2, {
    scheme: "exact",
    network: NANO_LIVE_NETWORK,
    asset: NANO_ASSET,
    amount: "1",
    payTo: "nano_3f5zmep1qax1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f9",
    maxTimeoutSeconds: 60,
    extra: { requestId: "req_x" },
  });
  assert.equal(result.x402Version, 2);
  assert.match(result.payload.paymentProof as string, /^[0-9A-F]{64}$/);
});

test("atomic claim store allows the proof exactly once (concurrent-safe)", async () => {
  const store = new InMemoryClaimStore();
  const key = consumptionKey("BA96F6", "req_r");
  const results = await Promise.all([store.claim(key), store.claim(key), store.claim(key)]);
  assert.deepEqual(results, [true, false, false]);
  assert.equal(await store.isClaimed(key), true);
});

test("fail-closed config: verify refuses outright when fewer than 2 endpoints", async () => {
  const config: NanoFacilitatorConfig = { rpc: { endpoints: [{ url: "https://never-used.invalid" }] } };
  const fac = new ExactNanoFacilitator(config);
  const res = await fac.verify(
    { x402Version: 2, accepted: reqs, payload: { paymentProof: "BA96F62D4EA651A21DA4282809F2541EA42481CA35018129F29B406EF3FE36C0" } },
    reqs,
  );
  assert.equal(res.isValid, false);
  assert.match(res.invalidReason ?? "", /fail-closed|independent|unconfirmed/i);
});