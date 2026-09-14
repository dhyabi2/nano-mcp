/**
 * x402 `exact`-on-`nano` SchemeNetworkServer.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * The server's job is to issue a one-time Nano address per request. It derives
 * the address deterministically from a server master seed plus the request id
 * (HKDF-SHA256), so the Nano address IS the memo: structurally replay-safe, no
 * trusted memo field, distinct across requests.
 */

import type {
    AssetAmount,
    Network,
    PaymentFlowConfig,
    PaymentRequirements,
    Price,
    SchemeNetworkServer,
    SupportedKind,
} from "@x402/core/types";

import { deriveOneTimeAddress } from "../../crypto";
import { NANO_ASSET, NANO_LIVE_NETWORK } from "../../types";

export interface NanoServerConfig {
    /** Server master secret: must be random, held only server-side, chmod 600. */
    masterSeed: Uint8Array;
}

export class ExactNanoScheme implements SchemeNetworkServer {
    readonly scheme = "exact";
    readonly defaultAssetTransferMethod = "default";
    constructor(private readonly config: NanoServerConfig) {}

    /** Nano has no on-wire ATMs; a single default flow. */
    readonly paymentFlows: Readonly<Record<string, PaymentFlowConfig>> = {
        default: { supported: ["upfront"], default: "upfront" },
    };

    /** XNO has 30 decimals. */
    getAssetDecimals(asset: string, network: Network): number | undefined {
        return network === NANO_LIVE_NETWORK && asset === NANO_ASSET ? 30 : undefined;
    }

    /**
     * Convert a price to the exact integer raw XNO amount. Only XNO on `nano:live`
     * is accepted: the raw amount = ceil(decimal XNO * 10^30), so the seller never
     * under-receives.
     */
    async parsePrice(price: Price, network: Network): Promise<AssetAmount> {
        if (network !== NANO_LIVE_NETWORK) {
            throw new Error(`nano server only serves ${NANO_LIVE_NETWORK}`);
        }
        if (typeof price === "object" && "asset" in price && "amount" in price) {
            return { asset: String(price.asset), amount: String(price.amount) };
        }
        const decimal = typeof price === "number" ? price.toFixed(30) : String(price);
        const raw = this.decimalToRaw(decimal);
        return { asset: NANO_ASSET, amount: raw.toString() };
    }

    /**
     * decimalToRaw("1.5") -> 1500000000000000000000000000000n. Rounds UP so the
     * server is never underpaid. Throws on NaN / negative input.
     */
    private decimalToRaw(decimal: string): bigint {
        const m = /^(\d+)(?:\.(\d+))?$/.exec(decimal.trim());
        if (!m) throw new Error(`cannot parse money amount: ${JSON.stringify(decimal)}`);
        const int = BigInt(m[1] ?? "0");
        const frac = (m[2] ?? "").padEnd(30, "0");
        if (frac.length > 30) throw new Error(`too many decimals for XNO: ${JSON.stringify(decimal)}`);
        return int * 10n ** 30n + BigInt(frac);
    }

    /**
     * Build the payment requirements for this request: network/asset/payTo are
     * set to the `nano:live` one-time address derived from the request id.
     */
    async enhancePaymentRequirements(
        paymentRequirements: PaymentRequirements,
        supportedKind: SupportedKind,
        _extensionKeys: string[],
    ): Promise<PaymentRequirements> {
        if (supportedKind.network !== NANO_LIVE_NETWORK) {
            throw new Error(`nano server does not support network ${supportedKind.network}`);
        }
        const requestId = String(paymentRequirements.extra?.requestId ?? "");
        if (!requestId) {
            throw new Error("nano `exact` requires extra.requestId to name the one-time address");
        }
        const payTo = deriveOneTimeAddress(this.config.masterSeed, requestId);
        return {
            ...paymentRequirements,
            scheme: "exact",
            network: NANO_LIVE_NETWORK,
            asset: NANO_ASSET,
            payTo,
            extra: { ...paymentRequirements.extra, requestId },
        };
    }
}