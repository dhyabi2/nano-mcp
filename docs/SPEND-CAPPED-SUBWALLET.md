# A spend-capped Nano sub-wallet, with the cap held by the operator

**For:** an operator whose agent may pay for things but whose compliance, finance or risk function wants a number
it can sign off: "this agent can never spend more than X, to these receivers". Several agents told us pre-approval
of spend is where their deals stall ("I have standing latitude to operate, but not to spend"). This is the shape
that makes the approval a standing policy instead of a request each time.

**Status:** a design and a decision function. `examples/spend_policy.py` decides allow or deny; it holds no key,
signs nothing and sends nothing. Wiring it to a signer is the operator's step, deliberately, and the design below
is what to check that wiring against.

## The rule that makes the cap real

The cap is enforced by the process that holds the sub-wallet's seed, never by the agent. The agent holds no seed
and cannot sign. It can only submit a payment request; the operator's script decides, and signs only on allow.
An agent that is mistaken, prompted by a stranger or hostile can ask for anything and still cannot spend past the
policy, because the thing that signs is not the thing that asks.

```
agent  --request {id, to, amount_raw}-->  operator script (holds seed)  --decide-->  allow? --sign+publish--> Nano
                                                 ^  append decision to ledger first, under a file lock
```

## The sub-wallet

- A separate account (a different index of the operator's seed, or its own seed) used only by this agent. The
  operator funds it with the most it is willing to lose, once. The balance is a second, independent ceiling: the
  policy can be wrong, the balance cannot be exceeded.
- The agent is given the sub-wallet's address (to receive refunds) and nothing else.

## The three policy lines

```
per_call_max_xno 0.01
daily_max_xno    0.10
allow            nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3
```

`allow` repeats, one line per receiver. A policy missing any of the three is refused; nothing is defaulted.

- **Per call:** one request over `per_call_max_xno` is denied (`over_per_call_cap`), exact to the raw.
- **Daily:** the sum of allowed requests since 00:00 UTC plus this one may not exceed `daily_max_xno`
  (`over_daily_cap`); the window resets at UTC midnight. A denied request does not consume any of it.
- **Receivers:** the destination must be on the list, compared as an account (the `nano_` and `xrb_` spellings of
  one key are one receiver), otherwise `receiver_not_allowed`.

## What the gate guarantees (each one is a test in `tests/test_spend_policy.py`)

1. Amounts are integer strings of raw. `1.5`, `1e30`, negatives, zero and floats are refused, never rounded.
2. Fail closed: a malformed request, an unreadable ledger or a ledger row it cannot count denies everything.
3. Idempotent: a repeated request `id` is `duplicate_request_id`, so an agent that retries after a timeout cannot pay twice.
4. The decision is appended to the ledger (JSON lines, mode 0600, fsync) before it is returned, under an exclusive
   lock held across read, decide and append: sixteen concurrent threads asking for 0.01 against a 0.025 daily cap
   produce exactly two allows.
5. On allow it returns only `sign_this = {to, amount_raw, id}` for the operator's own signer. Nothing else about the
   request reaches the signer, so a memo or extra field cannot change what is signed.
6. The module imports no wallet, signing or network code (checked by the test on the module's imports).

## Answering the custody and compliance objection

"Irreversible transfer, counterparty, routing, custody" are four separate worries; this addresses them as follows.
Irreversible: bounded by the caps and the funded balance, so the worst case is a number the operator chose.
Counterparty: only listed receivers can ever be paid. Routing: one hop, sender to listed receiver, on a public
ledger anyone can read. Custody: the operator holds the seed; the agent never does, so there is no agent-side
custody to attest to. The ledger is the audit trail.

## What this does not do

It does not stop the agent asking, and does not make a listed receiver trustworthy. It does not protect against a
compromised operator script or seed: they are the trust boundary. It is not a refund mechanism (a Nano send is
final; a refund is a new send the operator decides on). The daily window is UTC, not the operator's local day.
It is one process on one host with one ledger file; several signers need one shared ledger.

## Try it (offline)

```
python -m pytest -q tests/test_spend_policy.py
python - <<'PY'
import sys; sys.path.insert(0, "examples")
import spend_policy as sp
policy = sp.parse_policy(open("policy.txt").read())          # the three lines above
gate = sp.Gate(policy, "ledger.jsonl")
print(gate.handle({"id": "req-1", "to": "nano_...", "amount_raw": "10000000000000000000000000000"}))
PY
```
