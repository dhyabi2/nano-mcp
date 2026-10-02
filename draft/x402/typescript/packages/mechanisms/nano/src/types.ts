/**
 * Core Nano (XNO) types for the x402 `exact`-on-`nano` mechanism.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * Nano is an account-based network with a single native asset, XNO. It has no
 * smart contracts, so the `exact` settlement is *read-only* verification of a
 * client-submitted block hash against on-chain account history, cross-checked on
 * at least two independent RPC endpoints (strategy law L1).
 */

/**
 * Nano has 30 decimal places: 1 XNO = 10^30 raw. All wire amounts are the exact
 * raw integer represented as a decimal string.
 */
/** 1 XNO = 10^30 raw. */
export const NANO_RAW_PER_XNO: bigint = BigInt("10") ** BigInt(30);

/** The x402 network identifier (CAIP-ish) for Nano mainnet. */
export const NANO_LIVE_NETWORK = "nano:live";

/** The only Nano asset. There is no token contract. */
export const NANO_ASSET = "XNO";

/** Nano mainnet block hash / transaction id is 32 bytes -> 64 uppercase hex chars. */
export const NANO_BLOCK_HASH_HEX_LEN = 64;

/** Independence-defined typical public Nano RPC endpoints (reads are free). */
export const NANO_PUBLIC_RPC_ENDPOINTS = [
    "https://rpc.nano.to",
    "https://proxy.nano.rpc.blvd.run",
    "https://rpc.nano.community",
] as const;

/** A single RPC endpoint definition. */
export interface NanoRpcEndpoint {
    /** Absolute URL of a Nano-compatible JSON-RPC endpoint. */
    url: string;
    /** Optional API key header value (e.g. for rpc.nano.to). */
    apiKey?: string;
}

/** Independent RPC set used for fail-closed cross-checking. */
export interface NanoRpcConfig {
    /**
     * At least two independent endpoints. Verification FAILS CLOSED: if any
     * configured endpoint cannot confirm the block, the payment is refused.
     */
    endpoints: NanoRpcEndpoint[];
}

/** A confirmed Nano send that satisfies an `exact` requirement. */
export interface NanoConfirmedSend {
    /** The block hash (64 uppercase hex), i.e. the `paymentProof`. */
    blockHash: string;
    /** The account that signed the send (the payer). */
    payer: string;
    /** The exact raw amount moved, as a decimal string. */
    amount: string;
    /** The recipient account; MUST equal the requirement's `payTo`. */
    receiver: string;
    /** Confirmation status observed on-chain. */
    confirmed: true;
}

/** Result of a verification pass across the independent RPC set. */
export interface NanoVerificationResult {
    ok: boolean;
    /** Number of independent endpoints that confirmed the block. */
    confirmedOn: number;
    /** Total endpoints consulted (must be >= 2). */
    consulted: number;
    /** Human-readable reason when not ok, else undefined. */
    reason?: string;
    send?: NanoConfirmedSend;
}