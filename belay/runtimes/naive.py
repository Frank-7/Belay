"""Baseline 1. Retry the workflow on restart. No durable intent.

This is what most agent frameworks do today: a try/except with a retry, or
a supervisor that restarts the task. It writes an audit log, but the log
plays no part in recovery.

Included because it is the honest status quo, and because it establishes
that duplicate effects are not a hypothetical.
"""

from __future__ import annotations

from belay import chaos
from belay.authz import Denied
from belay.runtimes.base import Ctx, Outcome, Status

NAME = "naive"


def run(ctx: Ctx) -> Outcome:
    return _attempt(ctx, attempt=1)


def recover(ctx: Ctx) -> Outcome:
    # The only recovery strategy available: do it all again.
    return _attempt(ctx, attempt=2)


def _attempt(ctx: Ctx, attempt: int) -> Outcome:
    j = ctx.journal
    j.append("attempt_start", runtime=NAME, attempt=attempt)

    # Authorisation is checked once, up front, at planning time.
    try:
        ctx.perms.require("payments:refund")
    except Denied as d:
        j.append("refused", scope=d.scope, at="plan_time")
        return Outcome(Status.REFUSED, notes=[f"denied {d.scope} at plan time"])

    plan = ctx.agent.decide(ctx.order_id)
    chaos.maybe_crash("after_decide_before_journal")
    j.append("decided", plan=plan.as_dict(), invocation=ctx.agent.invocations)

    chaos.maybe_crash("after_intent")

    # No idempotency key of any kind is supplied, even where the service
    # would accept one. This is the gap we are measuring.
    if ctx.tier == "idempotent":
        receipt = ctx.payments.refund(
            ctx.order_id, plan.refund_cents, idem_key=f"attempt-{attempt}"
        )
    elif ctx.tier == "queryable":
        receipt = ctx.payments.refund(
            ctx.order_id, plan.refund_cents, client_ref=f"attempt-{attempt}"
        )
    else:
        receipt = ctx.payments.refund(ctx.order_id, plan.refund_cents)

    chaos.maybe_crash("after_ack_before_record")
    j.append("refund_recorded", external_id=receipt.external_id, amount=receipt.amount_cents)
    chaos.maybe_crash("after_effect_a_recorded")

    if plan.credit_cents:
        ctx.credits.issue(
            ctx.order_id, plan.credit_cents, idem_key=f"credit-attempt-{attempt}"
        )
        j.append("credit_recorded", amount=plan.credit_cents)

    j.append("committed", plan=plan.as_dict())
    return Outcome(
        Status.COMMITTED,
        reported_refund_cents=plan.refund_cents,
        reported_credit_cents=plan.credit_cents,
        plan_label=plan.label,
    )
