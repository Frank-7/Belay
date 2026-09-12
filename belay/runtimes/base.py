"""Shared plumbing for the four runtimes.

The runtimes deliberately do NOT share their run/recover logic. Each one is
written out linearly so a reader can see exactly what it does differently.
Only the context object and the resolution ladder live here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from belay.agent import RefundAgent
from belay.authz import PermissionStore
from belay.effects import Tier
from belay.journal import Journal
from services.ledger import Ledger
from services.payments import CreditService, NoSuchCapability
from services.payments import build as build_payments


class Status(str, Enum):
    COMMITTED = "committed"        # runtime believes the workflow completed
    ESCALATED = "escalated"        # runtime halted and asked for a human
    REFUSED = "refused"            # runtime declined (e.g. permission gone)
    CRASHED = "crashed"            # process died; no report written
    INCOMPLETE = "incomplete"      # ran out of steps without committing


@dataclass
class Outcome:
    status: Status
    reported_refund_cents: int | None = None
    reported_credit_cents: int | None = None
    plan_label: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "reported_refund_cents": self.reported_refund_cents,
            "reported_credit_cents": self.reported_credit_cents,
            "plan_label": self.plan_label,
            "notes": self.notes,
        }


class Unresolvable(Exception):
    """The service cannot tell us whether our effect committed, and
    retrying could duplicate it. Nothing in software fixes this."""


@dataclass
class Ctx:
    run_dir: str
    run_id: str
    order_id: str
    tier: str

    def __post_init__(self) -> None:
        self.journal = Journal(os.path.join(self.run_dir, "journal.jsonl"), self.run_id)
        self.ledger = Ledger(os.path.join(self.run_dir, "ledger.db"))
        self.perms = PermissionStore(os.path.join(self.run_dir, "perms.json"))
        self.payments = build_payments(self.tier, self.ledger)
        self.credits = CreditService(self.ledger)
        self.agent = RefundAgent()


def resolve_ambiguous_refund(ctx: Ctx, anchor: str, amount_cents: int):
    """The reconciliation ladder for an in-flight refund.

    This function is the honest core of the whole project. What we can do
    depends entirely on what the service offers; the runtime cannot invent
    a guarantee the service does not support.

    The ladder has two rungs and the distinction between them matters more
    than it looks:

      * A **query** asks the service what already happened. It creates
        nothing, so it needs no authorisation and is always safe.
      * A **completion** issues the effect because the query proved it never
        landed. That is a new external effect, so it needs the scope to be
        live, exactly as a first attempt would.

    An earlier version of this resolver collapsed the two on the idempotent
    tier, reasoning that re-issuing under the same anchor is idempotent and
    therefore safe. It is safe against *duplication* and unsafe against
    *authorisation*: if the original call never landed, the "retry" is the
    first and only call, and it was performed with no live permission.
    `experiments/run_revocation.py` caught this at a 50% rate. See
    FINDINGS.md, "A bug the harness found".
    """
    tier = ctx.payments.tier

    if tier is Tier.IDEMPOTENT:
        # Rung 1: pure query. The anchor is the key, so this is exact.
        found = ctx.payments.lookup(anchor)
        if found is not None:
            return found, "query_confirmed_committed"
        # Rung 2: it never landed. Completing it is a new effect.
        ctx.perms.require("payments:refund")
        receipt = ctx.payments.refund(ctx.order_id, amount_cents, idem_key=anchor)
        return receipt, "query_confirmed_absent_then_completed"

    if tier is Tier.QUERYABLE:
        found = ctx.payments.lookup(anchor)
        if found is not None:
            return found, "query_confirmed_committed"
        ctx.perms.require("payments:refund")
        receipt = ctx.payments.refund(ctx.order_id, amount_cents, client_ref=anchor)
        return receipt, "query_confirmed_absent_then_completed"

    # Tier.OPAQUE. There is no rung 1 here, and without it rung 2 is a coin
    # flip with someone else's money.
    try:
        ctx.payments.lookup(anchor)
    except NoSuchCapability:
        pass
    raise Unresolvable(
        "refund may or may not have committed; service offers neither "
        "idempotency nor lookup, so any retry risks a duplicate"
    )
