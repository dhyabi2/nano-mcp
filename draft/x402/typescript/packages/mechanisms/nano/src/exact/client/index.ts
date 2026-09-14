/**
 * x402 `exact`-on-`nano` SchemeNetworkClient.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * The client side of the `exact` scheme on Nano: it pays exactly `amount` raw
 * XNO to the one-time `payTo` via the agent's own Nano wallet, then presents the
 * on-chain block hash as `payload.paymentProof`. The block hash IS the payment
 * proof — the client's own send, confirmed on-chain (~1 s finality), feeless,
 * no issuer, no bridge, no trusted memo.
 */

import type {
    DefaultAsset,
    FindDefaultAsset,
    PaymentPayloadContext,
    PaymentPayloadResult,
    PaymentRequirements,
    SchemeClientHooks,
    SchemeNetworkClient,
} from "@x402/core/types";

import { NANO_ASSET, NANO_LIVE_NETWORK } from "../../types";
import type { NanoPayer } from "./payer";

const NANO_DEFAULT_ASSET: DefaultAsset = {
    asset: NANO_ASSET,
    decimals: 30,
    symbol: "XNO",
};

export class ExactNanoScheme implements SchemeNetworkClient {
    readonly scheme = "exact";
    readonly schemeHooks: SchemeClientHooks | undefined;

    constructor(
        private readonly payer: NanoPayer,
        schemeHooks?: SchemeClientHooks,
    ) {
        this.schemeHooks = schemeHooks;
    }

    /** Reverse lookup: XNO is the only Nano asset; undefined elsewhere. */
    readonly findDefaultAsset: FindDefaultAsset = (asset: string, network: string) => {
        if (network === NANO_LIVE_NETWORK && asset === NANO_ASSET) {
            return NANO_DEFAULT_ASSET;
        }
        return undefined;
    };

    private validate(pr: PaymentRequirements): void {
        if (pr.network !== NANO_LIVE_NETWORK) {
            throw new Error(`unsupported network ${pr.network}; expected ${NANO_LIVE_NETWORK}`);
        }
        if (pr.asset !== NANO_ASSET) {
            throw new Error(`unsupported asset ${pr.asset}; expected ${NANO_ASSET}`);
        }
        if (!pr.amount || pr.amount === "0") {
            throw new Error("payment requirements carry an invalid exact raw amount");
        }
        if (!/^nano_[13][13456789abcdefghijkmnopqrstuwxyz]+$/.test(pr.payTo)) {
            throw new Error(`payTo is not a Nano address: ${JSON.stringify(pr.payTo)}`);
        }
    }

    /**
     * Create the payment payload: ask the payer to send exactly `amount` raw to
     * `payTo`, then wrap the returned block hash as the 64-hex `paymentProof`.
     */
    async createPaymentPayload(
        x402Version: number,
        paymentRequirements: PaymentRequirements,
        _context?: PaymentPayloadContext,
    ): Promise<PaymentPayloadResult> {
        this.validate(paymentRequirements);
        const proof = await this.payer.pay(paymentRequirements.payTo, paymentRequirements.amount);
        if (!/^[0-9A-Fa-f]{64}$/.test(proof)) {
            throw new Error(`payer returned a non-64-hex paymentProof: ${JSON.stringify(proof)}`);
        }
        return { x402Version, payload: { paymentProof: proof } };
    }
}