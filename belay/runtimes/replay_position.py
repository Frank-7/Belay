"""Baseline 2. Deterministic replay, journaled results matched by step position.

This is the classic durable-execution recipe (Temporal, Cadence, Restate,
DBOS and friends, in the shape people actually write them). On recovery the
workflow function is re-executed from the top; a step whose result is
already in the journal returns that result instead of running again.

The soundness condition is stated plainly in every one of those systems'
docs: **workflow code must be deterministic.** Our workflow is not, because
the decision comes from a model. This file is here to show what that costs,
not to suggest the systems are badly built.

Position matching fails in a specific way: after the decision diverges, the
step at index i is no longer the same step it was, but the journal happily
hands back the old result. The runtime then reports an outcome that never
happened.
"""

from __future__ import annotations

import os

from belay import chaos
from belay.authz import Denied
from belay.runtimes.base import Ctx, Outcome, Status

NAME = "replay_position"

JOURNAL_DECISION = os.environ.get("BELAY_JOURNAL_DECISION", "1") == "1"


class _History:
    """Journaled step results, addressed by the order they occurred in."""

    def __init__(self, ctx: Ctx):
        self.results = [
            r for r in ctx.journal.read() if r["kind"] == "step_result"
        ]
        self.cursor = 0

    def next_for(self, _step_name: str):
        if self.cursor < len(self.results):
            rec = self.results[self.cursor]
            self.cursor += 1
            return rec["value"]
        self.cursor += 1
        return None


def run(ctx: Ctx) -> Outcome:
    return _execute(ctx, _History(ctx), replaying=False)


def recover(ctx: Ctx) -> Outcome:
    return _execute(ctx, _History(ctx), replaying=True)


def _execute(ctx: Ctx, hist: _History, replaying: bool) -> Outcome:
    j = ctx.journal
    j.append("attempt_start", runtime=NAME, replaying=replaying)

    # Step 1: authorisation, journaled as an activity result.
    cached = hist.next_for("authorize")
    if cached is None:
        try:
            ctx.perms.require("payments:refund")
        except Denied as d:
            j.append("refused", scope=d.scope, at="plan_time")
            return Outcome(Status.REFUSED, notes=[f"denied {d.scope} at plan time"])
        j.append("step_result", step="authorize", value={"granted": True})
    # On replay the cached grant is replayed as a deterministic fact. The
    # live permission state is never consulted again. This is invariant 2
    # failing, and it is a direct consequence of treating authorisation as
    # a journaled step.

    # Step 2: the decision. If its result is not in the journal, replay
    # re-invokes the agent, and the agent is not deterministic.
    if not JOURNAL_DECISION:
        plan = ctx.agent.decide(ctx.order_id)
        chaos.maybe_crash("after_decide_before_journal")
        plan_d = plan.as_dict()
        j.observe("inline_decision", plan=plan_d, durable=False)
    else:
        cached = hist.next_for("decide")
        if cached is None:
            plan = ctx.agent.decide(ctx.order_id)
            chaos.maybe_crash("after_decide_before_journal")
            j.append("step_result", step="decide", value=plan.as_dict())
            plan_d = plan.as_dict()
        else:
            plan_d = cached
    refund_cents = plan_d["refund_cents"]
    credit_cents = plan_d["credit_cents"]
    plan_label = plan_d["label"]

    chaos.maybe_crash("after_intent")

    # Step 3: the refund. Matched by position, so a diverged decision gets
    # the previous decision's receipt handed back to it.
    cached = hist.next_for("refund")
    if cached is None:
        receipt = _issue(ctx, refund_cents, key=f"wf-{ctx.run_id}-refund")
        chaos.maybe_crash("after_ack_before_record")
        j.append(
            "step_result",
            step="refund",
            value={"external_id": receipt.external_id, "amount": receipt.amount_cents},
        )
    else:
        # Silently accepting a receipt for a different amount than the
        # current plan calls for.
        pass

    chaos.maybe_crash("after_effect_a_recorded")

    # Step 4: the credit, which the previous run may not have needed at all.
    if credit_cents:
        cached = hist.next_for("credit")
        if cached is None:
            ctx.credits.issue(ctx.order_id, credit_cents, idem_key=f"wf-{ctx.run_id}-credit")
            j.append("step_result", step="credit", value={"amount": credit_cents})

    j.append("committed", plan=plan_d)
    return Outcome(
        Status.COMMITTED,
        reported_refund_cents=refund_cents,
        reported_credit_cents=credit_cents,
        plan_label=plan_label,
        notes=["replayed" if replaying else "first pass"],
    )


def _issue(ctx: Ctx, amount: int, key: str):
    if ctx.tier == "idempotent":
        return ctx.payments.refund(ctx.order_id, amount, idem_key=key)
    if ctx.tier == "queryable":
        return ctx.payments.refund(ctx.order_id, amount, client_ref=key)
    return ctx.payments.refund(ctx.order_id, amount)
