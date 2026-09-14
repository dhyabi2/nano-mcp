/**
 * @x402/nano — x402 `exact` scheme on the Nano (XNO) network.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * Symmetric to @x402/stellar: three entrypoints (client / server / facilitator),
 * each exporting `ExactNanoScheme` implementing the matching core interface.
 * Implements the same one-time-address, fail-closed-2-RPC, exactly-once-claim
 * semantics as the verified Python reference (nano-mcp).
 */

export { ExactNanoScheme as ExactNanoClient } from "./exact/client/index.js";
export { ExactNanoScheme as ExactNanoServer } from "./exact/server/index.js";
export { ExactNanoScheme as ExactNanoFacilitator } from "./exact/facilitator/index.js";

export type { NanoPayer } from "./exact/client/payer.js";
export { RecordingPayer } from "./exact/client/payer.js";
export type { NanoServerConfig } from "./exact/server/index.js";
export type { NanoFacilitatorConfig } from "./exact/facilitator/index.js";

export { InMemoryClaimStore, consumptionKey } from "./claim.js";
export type { ClaimStore } from "./claim.js";
export { verifyBlockOnIndependentEndpoints, buildFailClosedConfig, rpcCall, parseRaw } from "./rpc.js";
export {
    NANO_ASSET,
    NANO_LIVE_NETWORK,
    NANO_RAW_PER_XNO,
    NANO_PUBLIC_RPC_ENDPOINTS,
} from "./types.js";
export type { NanoRpcConfig, NanoRpcEndpoint, NanoConfirmedSend, NanoVerificationResult } from "./types.js";
export { deriveAccountKey, deriveOneTimeAddress, nanoAddress, nanoBase32Encode, generateMasterSeed, defaultSeedToPublicKey, seedToAccount } from "./crypto.js";
export type { SeedToPublicKey } from "./crypto.js";