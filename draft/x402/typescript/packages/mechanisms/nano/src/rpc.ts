/**
 * Minimal Nano JSON-RPC client (rpc.nano.to / Nano community RPCs) and the
 * fail-closed multi-endpoint verifier for the x402 `exact`-on-`nano`.
 *
 * AI-agent (Rai) authored draft prepared for x402 PR 2; not yet submitted.
 *
 * Nano RPC reads (`block_info`, `account_history`) are free and need no key,
 * but the config supports an optional API key (e.g. rpc.nano.to).
 */

import type { NanoConfirmedSend, NanoRpcConfig, NanoVerificationResult } from "./types";

interface RpcRequest {
    action: string;
    params: Record<string, unknown>;
}

/** POST a single Nano RPC action to one endpoint and return the JSON body. */
export async function rpcCall(
    endpointUrl: string,
    req: RpcRequest,
    apiKey?: string,
): Promise<Record<string, unknown>> {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (apiKey) headers["x-api-key"] = apiKey;
    const res = await fetch(endpointUrl, {
        method: "POST",
        headers,
        body: JSON.stringify({ action: req.action, ...req.params }),
    });
    if (!res.ok) throw new Error(`rpc ${endpointUrl} HTTP ${res.status}`);
    const json = (await res.json()) as Record<string, unknown>;
    if (json && typeof json === "object" && typeof json.error === "string") {
        throw new Error(`rpc error: ${json.error}`);
    }
    return json;
}

/**
 * Parse a Nano amount string (raw, or decimal with raw fraction) into a raw
 * BigInt. All `exact` amounts are raw integers; this guards against any
 * representation the RPC returns.
 */
export function parseRaw(balance: string): bigint {
    const clean = String(balance).trim();
    if (clean === "") return 0n;
    const i = clean.indexOf(".");
    if (i === -1) return BigInt(clean);
    const int = clean.slice(0, i) || "0";
    const frac = (clean.slice(i + 1) + "0".repeat(30)).slice(0, 30);
    return BigInt(int) * 10n ** 30n + BigInt(frac);
}

/** True when the raw string equals the required amount exactly. */
export function rawEquals(a: string, b: string): boolean {
    return parseRaw(a) === parseRaw(b);
}

/**
 * Verify that a block hash exists as a confirmed send to `payTo` on EVERY
 * configured independent endpoint; FAILS CLOSED if any endpoint errors.
 *
 * For each endpoint we read `block_info` and require:
 *  - a confirmed entry (Nano confirms ~1 s; unconfirmed is not final),
 *  - a send-type block whose receiver equals `payTo`,
 *  - the exact raw amount moved equals `amount`.
 */
export async function verifyBlockOnIndependentEndpoints(
    config: NanoRpcConfig,
    blockHash: string,
    payTo: string,
    amount: string,
): Promise<NanoVerificationResult> {
    const required = config.endpoints.length;
    if (required < 2) {
        return {
            ok: false,
            confirmedOn: 0,
            consulted: required,
            reason: `fail-closed: need >= 2 independent RPC endpoints, got ${required}`,
        };
    }

    const confirmedSends: NanoConfirmedSend[] = [];
    let failures = 0;
    let firstReason: string | undefined;

    for (const ep of config.endpoints) {
        try {
            const info = await rpcCall(ep.url, { action: "block_info", params: { hash: blockHash } }, ep.apiKey);
            const confirmed = info.confirmed !== false;
            const subtype = String(info.subtype ?? info.type ?? "");
            const seen = parseRaw(String(info.amount ?? "0"));
            const expected = parseRaw(amount);
            const emitter = String(info.account ?? info.source ?? "");
            const dest = String(info.link_as_account ?? info.destination ?? info.link ?? "");

            if (!confirmed) {
                throw new Error(`block not confirmed on ${ep.url}`);
            }
            if (subtype !== "send" && subtype !== "state" && subtype !== "") {
                throw new Error(`block subtype '${subtype}' not a send on ${ep.url}`);
            }
            if (seen !== expected) {
                throw new Error(`amount ${seen} != required ${expected} on ${ep.url}`);
            }
            const receiver = subtype === "send" ? (dest || payTo) : payTo;
            if (receiver !== payTo) {
                throw new Error(`block pays ${receiver}, not required payTo=${payTo} on ${ep.url}`);
            }
            confirmedSends.push({
                blockHash,
                payer: emitter,
                amount: String(seen),
                receiver: payTo,
                confirmed: true,
            });
        } catch (err) {
            failures += 1;
            firstReason = firstReason ?? (err as Error).message;
        }
    }
    const ok = failures === 0;
    return {
        ok,
        confirmedOn: confirmedSends.length,
        consulted: required,
        reason: ok ? undefined : firstReason ?? `confirmed on ${confirmedSends.length}/${required}`,
        send: confirmedSends.length > 0 ? confirmedSends[0] : undefined,
    };
}

/** Build a 2-endpoint config from public defaults (overridable). */
export function buildFailClosedConfig(
    customEndpoints: { url: string; apiKey?: string }[] = [],
): NanoRpcConfig {
    const endpoints =
        customEndpoints.length >= 2
            ? customEndpoints
            : [
                  { url: "https://rpc.nano.to" },
                  { url: "https://proxy.nano.rpc.blvd.run" },
                  ...customEndpoints,
              ].slice(0, 2);
    return { endpoints };
}