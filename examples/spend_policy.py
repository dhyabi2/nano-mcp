"""Spend policy for an operator-held sub-wallet: decisions only. This file never signs, sends or holds a key.

The agent can ask for a payment; the OPERATOR'S script (the process that holds the sub-wallet seed) runs `Gate.handle`
and signs only when it answers allow. The cap lives in that script, so an agent that is prompted, buggy or hostile can
ask for anything and still cannot spend past it. See docs/SPEND-CAPPED-SUBWALLET.md.

Three policy lines (a policy missing any of them is refused; there are no defaults):

    per_call_max_xno 0.01
    daily_max_xno    0.10
    allow            nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3     (repeat for each receiver)

Every decision is appended to a JSON-lines ledger BEFORE it is returned, under an exclusive file lock, so two concurrent
requests cannot both fit under the same remaining cap. Anything unreadable fails closed.
"""
import fcntl
import json
import os
import threading
from datetime import datetime, timezone

from nano_sdk.crypto import public_key_from_address
from nano_sdk.units import nano_to_raw


class PolicyError(ValueError):
    pass


def parse_policy(text):
    """-> {"per_call_max_raw": int, "daily_max_raw": int, "allow": [pubkey bytes...], "allow_text": [address...]}"""
    per_call = daily = None
    allow, allow_text = [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise PolicyError("line %d: expected `<name> <value>`, got %r" % (n, line))
        name, value = parts
        if name in ("per_call_max_xno", "daily_max_xno"):
            if not value.replace(".", "", 1).isdigit():
                raise PolicyError("line %d: %s must be a plain decimal, got %r" % (n, name, value))
            raw = nano_to_raw(value)
            if raw <= 0:
                raise PolicyError("line %d: %s must be positive" % (n, name))
            if name == "per_call_max_xno":
                if per_call is not None:
                    raise PolicyError("line %d: per_call_max_xno given twice" % n)
                per_call = raw
            else:
                if daily is not None:
                    raise PolicyError("line %d: daily_max_xno given twice" % n)
                daily = raw
        elif name == "allow":
            try:
                key = public_key_from_address(value)
            except ValueError as exc:
                raise PolicyError("line %d: allow address rejected: %s" % (n, exc))
            if key not in allow:
                allow.append(key)
                allow_text.append(value)
        else:
            raise PolicyError("line %d: unknown policy line %r" % (n, name))
    if per_call is None or daily is None or not allow:
        raise PolicyError("a policy needs per_call_max_xno, daily_max_xno and at least one allow line; none is defaulted")
    if per_call > daily:
        raise PolicyError("per_call_max_xno is larger than daily_max_xno")
    return {"per_call_max_raw": per_call, "daily_max_raw": daily, "allow": allow, "allow_text": allow_text}


def _day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def decide(policy, request, approved, now):
    """Pure. `approved` is the earlier ALLOW records (dicts with id, amount_raw, at). Returns {"allow": bool, "reason": str, ...}."""
    if not isinstance(request, dict):
        return {"allow": False, "reason": "malformed_request"}
    rid, to, amount = request.get("id"), request.get("to"), request.get("amount_raw")
    if not isinstance(rid, str) or not rid or len(rid) > 128:
        return {"allow": False, "reason": "malformed_request", "detail": "id must be a non-empty string"}
    if not isinstance(amount, str) or not amount.isdigit() or int(amount) <= 0 or len(amount) > 39:
        return {"allow": False, "reason": "malformed_request", "detail": "amount_raw must be a positive integer string"}
    if any(r.get("id") == rid for r in approved):
        return {"allow": False, "reason": "duplicate_request_id"}
    try:
        key = public_key_from_address(to)
    except ValueError:
        return {"allow": False, "reason": "malformed_request", "detail": "to is not a valid address"}
    if key not in policy["allow"]:
        return {"allow": False, "reason": "receiver_not_allowed"}
    raw = int(amount)
    if raw > policy["per_call_max_raw"]:
        return {"allow": False, "reason": "over_per_call_cap", "per_call_max_raw": str(policy["per_call_max_raw"])}
    today = _day(now)
    spent = sum(int(r["amount_raw"]) for r in approved if _day(r["at"]) == today)
    if spent + raw > policy["daily_max_raw"]:
        return {"allow": False, "reason": "over_daily_cap", "spent_today_raw": str(spent),
                "remaining_today_raw": str(policy["daily_max_raw"] - spent)}
    return {"allow": True, "reason": "within_policy", "remaining_today_raw": str(policy["daily_max_raw"] - spent - raw)}


class Gate:
    """The operator's side. `handle` returns the decision and, on allow, the exact parameters the operator's own signer
    may sign. Signing is not here and is not the agent's."""

    _locks = {}
    _guard = threading.Lock()

    def __init__(self, policy, ledger_path, clock=None):
        self.policy, self.path = policy, ledger_path
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

    def _thread_lock(self):
        with Gate._guard:
            return Gate._locks.setdefault(os.path.abspath(self.path), threading.Lock())

    def handle(self, request):
        now = self.clock()
        with self._thread_lock():
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                with os.fdopen(os.dup(fd), "r", encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
                approved = []
                for line in lines:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        return {"allow": False, "reason": "ledger_unreadable"}       # fail closed
                    if rec.get("allow") and isinstance(rec.get("amount_raw"), str) and isinstance(rec.get("at"), (int, float)):
                        approved.append(rec)
                    elif rec.get("allow"):
                        return {"allow": False, "reason": "ledger_unreadable"}
                verdict = decide(self.policy, request, approved, now)
                record = dict(verdict, at=now, id=(request or {}).get("id") if isinstance(request, dict) else None,
                              to=(request or {}).get("to") if isinstance(request, dict) else None,
                              amount_raw=(request or {}).get("amount_raw") if isinstance(request, dict) else None)
                os.lseek(fd, 0, os.SEEK_END)
                os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        if verdict["allow"]:
            verdict = dict(verdict, sign_this={"to": request["to"], "amount_raw": request["amount_raw"], "id": request["id"]})
        return verdict
