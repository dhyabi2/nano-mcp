/**
 * x402 `exact`-on-`nano` SchemeNetworkFacilitator.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * The facilitator does NOT move, wrap or guard any funds — Nano has no smart
 * contracts and no facilitator-controlled addresses. Its only jobs:
 *  1. VERIFY that the presented block hash is a confirmed send to `payTo` of
 *     exactly `amount` XNO, cross-checked on AT LEAST TWO INDEPENDENT RPC
 *     endpoints, FAILING CLOSED if any endpoint cannot confirm (strategy law L1).
 *  2. SETTLE by re-running full verification (never trusts the prior /verify),
 *     then binding the proof to the request with an ATOMIC SINGLE-USE claim, so
 *     one proof yields one resource, exactly once.
 */

import type {
    FacilitatorContext,
    Network,
    PaymentPayload,
    PaymentRequirements,
    SchemeNetworkFacilitator,
    SettleResponse,
    VerifyResponse,
} from "@x402/core/types";

import { InMemoryClaimStore, consumptionKey, type ClaimStore } from "../../claim";
import { verifyBlockOnIndependentEndpoints } from "../../rpc";
import { NANO_ASSET, NANO_LIVE_NETWORK, type NanoRpcConfig } from "../../types";

export interface NanoFacilitatorConfig {
    /** At least two independent RPC endpoints; single-RPC outage fails closed. */
    rpc: NanoRpcConfig;
    /** Claim store; defaults to an in-memory singleton (SQLite in production). */
    claimStore?: ClaimStore;
}

export class ExactNanoScheme implements SchemeNetworkFacilitator {
    readonly scheme = "exact";
    readonly caipFamily = "nano:*";
    private readonly claimStore: ClaimStore;

    constructor(private readonly config: NanoFacilitatorConfig) {
        this.claimStore = config.claimStore ?? new InMemoryClaimStore();
    }

    /** No extra data: unlike fee-markets there is no sponsor/feePayer surface. */
    getExtra(_network: Network): Record<string, unknown> | undefined {
        return undefined;
    }

    /** No facilitator-controlled addresses (nothing for the facilitator to sign). */
    getSigners(_network: string): string[] {
        return [];
    }

    /**
     * Verify the payment: the block hash must confirm on every independent RPC
     * endpoint as a send to `payTo` of exactly `amount` XNO.
     */
    async verify(
        payload: PaymentPayload,
        requirements: PaymentRequirements,
        _context?: FacilitatorContext,
    ): Promise<VerifyResponse> {
        const proof = String(payload.payload?.paymentProof ?? "");
        const reqCheck = this.checkRequirements(requirements, payload);
        if (reqCheck) return reqCheck;
        if (!/^[0-9A-Fa-f]{64}$/.test(proof)) {
            return { isValid: false, invalidReason: "proof missing", invalidMessage: "payload.paymentProof must be a 64-hex Nano block hash" };
        }
        const res = await verifyBlockOnIndependentEndpoints(
            this.config.rpc,
            proof,
            requirements.payTo,
            requirements.amount,
        );
        if (!res.ok) {
            return {
                isValid: false,
                invalidReason: "unconfirmed",
                invalidMessage: res.reason ?? "proof not confirmed on all independent RPC endpoints",
                extra: { confirmedOn: res.confirmedOn, consulted: res.consulted },
            };
        }
        return {
            isValid: true,
            payer: res.send?.payer,
            extra: { confirmedOn: res.confirmedOn, consulted: res.consulted, amount: res.send?.amount },
        };
    }

    /**
     * Settle: re-run FULL verification (never trust a prior /verify), then bind
     * the proof to this request exactly once. Returns the verified on-chain block.
     */
    async settle(
        payload: PaymentPayload,
        requirements: PaymentRequirements,
        _context?: FacilitatorContext,
    ): Promise<SettleResponse> {
        const proof = String(payload.payload?.paymentProof ?? "");
        const reqCheck = this.checkRequirements(requirements, payload);
        if (reqCheck) {
            return { success: false, errorReason: "invalid", errorMessage: "requirements inconsistent", transaction: proof, network: NANO_LIVE_NETWORK };
        }
        if (!/^[0-9A-Fa-f]{64}$/.test(proof)) {
            return { success: false, errorReason: "invalid", errorMessage: "bad paymentProof", transaction: proof, network: NANO_LIVE_NETWORK };
        }

        // 1. Re-verify on-chain (MUST NOT trust the earlier /verify result).
        const res = await verifyBlockOnIndependentEndpoints(
            this.config.rpc,
            proof,
            requirements.payTo,
            requirements.amount,
        );
        if (!res.ok || !res.send) {
            return {
                success: false,
                errorReason: "unconfirmed",
                errorMessage: res.reason ?? "not verified on all endpoints",
                transaction: proof,
                network: NANO_LIVE_NETWORK,
            };
        }

        // 2. Atomic single-use claim (exactly-one-wins, replay-safe across restarts).
        const requestId = String(requirements.extra?.requestId ?? "");
        const key = consumptionKey(proof, requestId);
        const claimed = await this.claimStore.claim(key);
        if (!claimed) {
            return { success: false, errorReason: "duplicate", errorMessage: "paymentProof already claimed for this request", transaction: proof, network: NANO_LIVE_NETWORK };
        }

        return {
            success: true,
            transaction: proof,
            network: NANO_LIVE_NETWORK,
            payer: res.send.payer,
            amount: res.send.amount,
        };
    }

    private checkRequirements(
        requirements: PaymentRequirements,
        payload: PaymentPayload,
    ): VerifyResponse | null {
        if (requirements.scheme !== "exact") {
            return { isValid: false, invalidReason: "bad-scheme", invalidMessage: `scheme must be exact` };
        }
        if (requirements.network !== NANO_LIVE_NETWORK || payload.accepted?.network !== NANO_LIVE_NETWORK) {
            return { isValid: false, invalidReason: "bad-network", invalidMessage: `network must be ${NANO_LIVE_NETWORK}` };
        }
        if (requirements.asset !== NANO_ASSET || payload.accepted?.asset !== NANO_ASSET) {
            return { isValid: false, invalidReason: "bad-asset", invalidMessage: `asset must be ${NANO_ASSET}` };
        }
        if (requirements.amount !== payload.accepted?.amount) {
            return { isValid: false, invalidReason: "bad-amount", invalidMessage: "amount mismatch between requirements and accepted" };
        }
        if (requirements.payTo !== payload.accepted?.payTo) {
            return { isValid: false, invalidReason: "bad-payto", invalidMessage: "payTo mismatch between requirements and accepted" };
        }
        return null;
    }
}