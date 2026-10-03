/**
 * Nano payer abstraction — the boundary between the x402 mechanism and the
 * agent's own Nano wallet/SDK.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * In the `exact`-on-`nano` scheme the client signs a Nano *send* block locally,
 * gets PoW via a Nano RPC `work_generate`, broadcasts via `process`, and presents
 * the resulting block hash as `payload.paymentProof`. The actual sign+PoW+publish
 * pipeline (Ed25519-Blake2b signing, base32 address, state-block bytes) lives in
 * the agent's self-custody SDK (nano-mcp `nano_sdk`), verified against
 * docs.nano.org and the live chain. This interface is the mechanism's boundary;
 * implement it with your own verified wallet rather than re-deriving crypto.
 */

export interface NanoPayer {
    /**
     * Send exactly `amountRaw` XNO to `payTo`. Returns the new block hash
     * (64 uppercase hex) — the `paymentProof`. Must throw if it cannot.
     */
    pay(payTo: string, amountRaw: string): Promise<string>;
}

/** Test payer that trusts `pays` to scan history (no real broadcast). */
export class RecordingPayer implements NanoPayer {
    readonly records: { payTo: string; amountRaw: string; blockHash: string }[] = [];
    constructor(private readonly makeHash: (payTo: string, amount: string) => string) {}
    async pay(payTo: string, amountRaw: string): Promise<string> {
        const hash = this.makeHash(payTo, amountRaw);
        this.records.push({ payTo, amountRaw, blockHash: hash });
        return hash;
    }
}