/**
 * Atomic single-use claim store for x402 `exact`-on-`nano` settlement.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * A proof (block hash) must be claimed atomically before the resource executes;
 * of two concurrent presentations of the same proof for the same request exactly
 * one may succeed. The canonical consumption key is `nano:live <block-hash>
 * <requestId>` (spec § Replay / single-use claim).
 *
 * This in-memory implementation is the STUB for the SQLite store the production
 * facilitator uses (nano-mcp's `store.py` implements the same exact-once semantics
 * with `INSERT ... PRIMARY KEY`). Swap the backend by implementing `ClaimStore`.
 */

export interface ClaimStore {
    /** Atomically claim `key`. Resolves true if this call won; false if already claimed. */
    claim(key: string): Promise<boolean>;
    /** Whether the key is already claimed. */
    isClaimed(key: string): Promise<boolean>;
}

/** In-memory, concurrency-safe claim store (single-process). */
export class InMemoryClaimStore implements ClaimStore {
    private readonly claimed = new Set<string>();
    private tail: Promise<void> = Promise.resolve();

    /** Serialize claim attempts so two concurrent calls resolve atomically. */
    async claim(key: string): Promise<boolean> {
        let result = false;
        this.tail = this.tail.then(() => {
            if (!this.claimed.has(key)) {
                this.claimed.add(key);
                result = true;
            }
        });
        await this.tail;
        return result;
    }

    async isClaimed(key: string): Promise<boolean> {
        return this.claimed.has(key);
    }
}

/** Build the canonical consumption key for a proof + request. */
export function consumptionKey(blockHash: string, requestId: string): string {
    return `nano:live ${blockHash} ${requestId}`;
}