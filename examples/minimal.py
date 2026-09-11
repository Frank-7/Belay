#!/usr/bin/env python3
"""The anchoring pattern applied to a workflow that is not the refund one.

Belay's runtime is a research artifact, not a general library: the workflow
in `belay/runtimes/anchored.py` has its effect slots hard-coded, because the
point was to measure a guarantee rather than to ship an abstraction. So the
thing to take away is the *pattern*, and this file is the pattern at its
smallest.

The workflow: charge a card, then email a receipt. Two effects, one of them
irreversible, and a model deciding the amount.

Run it:

    python3 examples/minimal.py            # clean pass
    BELAY_CRASH_AT=in_flight python3 examples/minimal.py   # crash, then recover

The three rules, and where each appears below:

  1. Effect slots are enumerated and anchored BEFORE the model is consulted.
     -> `SLOTS`, and the `anchor` writes in `workflow()` before `decide()`.
  2. Recovery reads the journal; it does not re-derive intent by re-running.
     -> `read_state()`, and the fact that `decide()` is guarded by it.
  3. Ambiguity the service cannot resolve is escalated, not guessed.
     -> `reconcile()` raising, rather than retrying.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay import chaos  # noqa: E402
from belay.authz import Denied, PermissionStore  # noqa: E402
from belay.journal import Journal  # noqa: E402

# Rule 1. Fixed before any model output is consulted. A model that asks for
# an effect outside this set gets refused, not accommodated.
SLOTS = ("charge", "receipt_email")


# ---------------------------------------------------------------------------
# A stand-in payment API. Idempotent on a caller key, and able to answer
# "did you ever see key K?" - i.e. the `queryable`+`idempotent` tier.
# ---------------------------------------------------------------------------
class CardAPI:
    def __init__(self, state_path: str):
        self.path = state_path

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, d: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
            fh.flush()
            os.fsync(fh.fileno())

    def lookup(self, key: str) -> dict | None:
        """A pure query. Creates nothing, needs no permission."""
        return self._load().get(key)

    def charge(self, key: str, cents: int) -> dict:
        d = self._load()
        if key in d:
            return {**d[key], "deduped": True}
        d[key] = {"key": key, "cents": cents}
        self._save(d)
        # The crash window: the charge is real, the caller has not heard back.
        chaos.maybe_crash("in_flight")
        return d[key]


class Unresolvable(Exception):
    pass


# ---------------------------------------------------------------------------
# The runtime
# ---------------------------------------------------------------------------
def read_state(journal: Journal) -> dict:
    """Rule 2. Project the journal. No workflow code is re-executed to
    reconstruct what was meant; the journal is the record of intent."""
    st: dict = {"anchors": {}, "intents": {}, "settled": {}, "plan": None}
    for r in journal.read():
        if r["kind"] == "anchor":
            st["anchors"][r["slot"]] = r["anchor"]
        elif r["kind"] == "decided":
            st["plan"] = r["plan"]
        elif r["kind"] == "intent":
            st["intents"][r["slot"]] = r
        elif r["kind"] == "settled":
            st["settled"][r["slot"]] = r
    return st


def reconcile(api: CardAPI, perms: PermissionStore, intent: dict) -> tuple[dict, str]:
    """Rule 3, and the query/completion split that took us a bug to learn.

    Asking the API what happened is free and always safe. Issuing the charge
    because the query proved it never landed is a NEW effect, and needs the
    scope to be live exactly as a first attempt would.
    """
    found = api.lookup(intent["anchor"])
    if found is not None:
        return found, "query_confirmed_committed"

    # It never landed. Completing it is a new effect.
    perms.require("cards:charge")
    return api.charge(intent["anchor"], intent["amount"]), "confirmed_absent_then_completed"


def decide(order_id: str) -> dict:
    """Stand-in for a model call. Nondeterministic on purpose: a recovering
    process draws independently of the one that crashed."""
    import random

    rng = random.Random(os.urandom(8))
    cents = rng.choice([1999, 2499])
    return {"cents": cents, "email": "receipt@example.com"}


def workflow(run_dir: str, run_id: str) -> str:
    journal = Journal(os.path.join(run_dir, "journal.jsonl"), run_id)
    perms = PermissionStore(os.path.join(run_dir, "perms.json"))
    api = CardAPI(os.path.join(run_dir, "card_state.json"))
    st = read_state(journal)
    recovering = bool(st["anchors"])

    journal.append("attempt_start", recovering=recovering)

    if not recovering:
        # Rule 1. Anchors first. These fsyncs happen before `decide()` is
        # ever called, which is the entire trick.
        for slot in SLOTS:
            journal.append("anchor", slot=slot, anchor=uuid.uuid4().hex)
        st = read_state(journal)

    # Rule 3, first. Anything in flight is settled before the workflow moves.
    for slot, intent in st["intents"].items():
        if slot in st["settled"] or slot != "charge":
            continue
        try:
            receipt, method = reconcile(api, perms, intent)
        except Denied as d:
            journal.append("refused", scope=d.scope, at="reconciliation")
            return f"REFUSED: charge never landed and {d.scope} was revoked"
        except Unresolvable as u:
            journal.append("escalated", reason=str(u))
            return f"ESCALATED: {u}"
        journal.append("settled", slot=slot, anchor=intent["anchor"],
                       amount=receipt["cents"], method=method)
        st = read_state(journal)

    # Rule 2. The journaled decision wins. We only ask the model again when
    # the journal proves no intent was ever durable.
    if st["plan"] is None:
        if st["intents"]:
            journal.append("escalated", reason="intent without a durable decision")
            return "ESCALATED: an effect was attempted but we cannot know what else was intended"
        plan = decide("order-1")
        journal.append("decided", plan=plan)
        st = read_state(journal)

    plan = st["plan"]

    # ---- charge slot ----
    if "charge" not in st["settled"]:
        anchor = st["anchors"]["charge"]
        try:
            perms.require("cards:charge")     # live read, at the instant of use
        except Denied as d:
            journal.append("refused", scope=d.scope, at="execution_time")
            return f"REFUSED: {d.scope} not held at execution time"
        journal.append("intent", slot="charge", anchor=anchor, amount=plan["cents"])
        chaos.maybe_crash("after_intent")   # intent durable, nothing sent yet
        receipt = api.charge(anchor, plan["cents"])
        journal.append("settled", slot="charge", anchor=anchor,
                       amount=receipt["cents"], method="first_attempt")

    # ---- receipt slot ----
    if "receipt_email" not in st["settled"]:
        anchor = st["anchors"]["receipt_email"]
        journal.append("intent", slot="receipt_email", anchor=anchor, amount=0)
        journal.append("settled", slot="receipt_email", anchor=anchor,
                       amount=0, method="sent")

    journal.append("committed", plan=plan)
    return f"COMMITTED: charged {plan['cents']} cents once"


# ---------------------------------------------------------------------------
def main() -> int:
    chaos.arm_from_env()

    if os.environ.get("BELAY_CHILD"):
        run_dir = os.environ["BELAY_RUN_DIR"]
        print(workflow(run_dir, os.environ["BELAY_RUN_ID"]))
        return 0

    # Parent: run, observe the crash, recover, then check the card API.
    run_dir = tempfile.mkdtemp(prefix="belay-example-")
    run_id = uuid.uuid4().hex[:8]
    PermissionStore(os.path.join(run_dir, "perms.json")).grant_all(["cards:charge"])
    crash_at = os.environ.get("BELAY_CRASH_AT", "none")

    env = {**os.environ, "BELAY_CHILD": "1", "BELAY_RUN_DIR": run_dir,
           "BELAY_RUN_ID": run_id}

    print(f"crash point: {crash_at}\n")
    p = subprocess.run([sys.executable, __file__], env=env,
                       capture_output=True, text=True)
    print("first pass: ", p.stdout.strip() or f"<killed, exit {p.returncode}>")

    if p.returncode == -9:
        p2 = subprocess.run([sys.executable, __file__],
                            env={**env, "BELAY_CRASH_AT": "none"},
                            capture_output=True, text=True)
        print("recovery:   ", p2.stdout.strip())

    charges = json.load(open(os.path.join(run_dir, "card_state.json"))) \
        if os.path.exists(os.path.join(run_dir, "card_state.json")) else {}
    total = sum(c["cents"] for c in charges.values())
    print(f"\ncard API saw {len(charges)} charge(s), {total} cents total")
    print("PASS: charged at most once" if len(charges) <= 1
          else "FAIL: duplicate charge")
    return 0 if len(charges) <= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
