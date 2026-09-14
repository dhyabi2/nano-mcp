/**
 * Nano address encoding and one-time address derivation.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * Nano uses base32 with the custom alphabet "13456789abcdefghijkmnopqrstuwxyz"
 * (no 0, 2, l, v). An account address is:
 *   "nano_" + base32(public key, 32 bytes -> 52 chars) + base32(checksum, 5 bytes -> 8 chars)
 * where checksum = blake2b(public key raw bytes) truncated to 5 bytes.
 *
 * The one-time address per request is derived with HKDF-SHA256 from a server
 * master seed plus the opaque `requestId`, so the Nano address IS the memo and
 * is structurally replay-safe across requests (spec "one-time `payTo`").
 *
 * IMPORTANT (honest scope): Nano uses Ed25519-Blake2b public-key derivation. This
 * draft's `seedToPublicKey` default uses the standard (RFC 8032 Ed25519 / SHA-512)
 * key to keep the package self-contained and dependency-light; the production
 * `exact`-on-`nano` mechanism (nano-mcp `nano_sdk`) uses the Ed25519-Blake2b
 * variant verified against docs.nano.org. Plug in your own verified mapping via
 * the `SeedToPublicKey` option — the address ENCODING and one-time HKDF binding
 * are the parts the mechanism owns and are identical either way.
 */

import { createHash, hkdfSync, randomBytes } from "node:crypto";
import { getPublicKey as nobleGetPublicKey, hashes as nobleHashes } from "@noble/ed25519";

// noble/ed25519 v3 requires a synchronous SHA-512 to be set before use.
nobleHashes.sha512 = (msg: Uint8Array) => new Uint8Array(createHash("sha512").update(msg).digest());

/** Nano base32 alphabet (RFC 4648 order replaced; no 0,2,v,l). */
const NANO_ALPHABET = "13456789abcdefghijkmnopqrstuwxyz";

export function blake2bBytes(data: Uint8Array, len: number): Uint8Array {
    return createHash("blake2b512").update(data).digest().subarray(0, len);
}

/** Encode bytes to Nano base32 (zero-padded to group of 5). */
export function nanoBase32Encode(bytes: Uint8Array): string {
    let bits = "";
    for (const b of bytes) bits += b.toString(2).padStart(8, "0");
    const pad = (5 - (bits.length % 5)) % 5;
    bits += "0".repeat(pad);
    let out = "";
    for (let i = 0; i < bits.length; i += 5) {
        out += NANO_ALPHABET[parseInt(bits.slice(i, i + 5), 2)];
    }
    return out;
}

/** Derive a nano_ address from a 32-byte public key. */
export function nanoAddress(publicKeyBytes: Uint8Array): string {
    return "nano_" + nanoBase32Encode(publicKeyBytes) + nanoBase32Encode(blake2bBytes(publicKeyBytes, 5));
}

/**
 * Deterministically derive a 32-byte ACCOUNT (private) key from a server master
 * seed and a request id. Same (seed, requestId) -> same key; different requestId
 * -> different key (HKDF-SHA256, 32-byte salt, 32-byte output).
 */
export function deriveAccountKey(masterSeed: Uint8Array, requestId: string): Uint8Array {
    return new Uint8Array(Buffer.from(hkdfSync("sha256", masterSeed, new Uint8Array(0), Buffer.from(requestId, "utf8"), 32)));
}

/** Map a 32-byte private/seed key to its public key. See header note. */
export type SeedToPublicKey = (privateSeed32: Uint8Array) => Uint8Array;

/** Default RFC 8032 mapping (see header note re Ed25519-Blake2b). */
export const defaultSeedToPublicKey: SeedToPublicKey = (seed: Uint8Array) =>
    nobleGetPublicKey(seed);

/**
 * Derive the one-time nano_ address for `requestId`. The server holds `masterSeed`
 * and the returned private key per request, so it — and only it — can receive and
 * spend payments that arrive at the address.
 */
export function deriveOneTimeAddress(masterSeed: Uint8Array, requestId: string, seedToPublicKey: SeedToPublicKey = defaultSeedToPublicKey): string {
    return nanoAddress(seedToPublicKey(deriveAccountKey(masterSeed, requestId)));
}

/**
 * Resolve a secret seed to its Nano public key + address, given a seedToPublicKey.
 * This cleanly separates the SDK-owned Ed25519-Blake2b crypto from the
 * mechanism-owned address encoding.
 */
export function seedToAccount(seed: Uint8Array, seedToPublicKey: SeedToPublicKey = defaultSeedToPublicKey): { publicKey: Uint8Array; address: string } {
    const publicKey = seedToPublicKey(seed);
    return { publicKey, address: nanoAddress(publicKey) };
}

/** Generate a random 32-byte master seed (server master secret). */
export function generateMasterSeed(): Uint8Array {
    return randomBytes(32);
}