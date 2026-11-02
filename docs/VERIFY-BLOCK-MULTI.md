# verify_block_multi - do not trust one public node

An agent with no node of its own reads the chain through someone else's endpoint. This asks several and passes only
when they agree, and it does not take their word for the fields: it recomputes the state-block hash from the returned
contents and requires it to equal the hash you asked about.

    git clone https://github.com/dhyabi2/nano-mcp && python3 nano-mcp/nano_mcp/verify_multi.py B749B757EE750FC9AEA72F33CB429EACCD2ABEC9F2CCF59BF17AFAC304C9A58F

Output: `verdict` (pass/fail), `why`, and `nodes[]` listing every node asked with `status` (ok / missing / error /
unconfirmed / lied). Exit 0 pass, 1 fail. Options: `--node URL` (repeat to choose your own set), `--min-agree N`
(default 3), `--payee nano_...`, `--amount-raw N`. As an MCP tool it is `verify_block_multi`.

Trust assumptions, said plainly: it removes "one node lied or was stale" and "a proxy answered with something that is
not a block". It does NOT check the ed25519 signature (no crypto dependency, stdlib only) and cannot show that the
nodes are run by different parties - choose the set. For a local-ledger check, run your own node and pass it as
`--node`. Read-only: no key, seed or signing anywhere.
