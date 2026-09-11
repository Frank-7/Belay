"""Baseline 3. Replay, with journaled results matched by content hash.

This is the *better* engineering instinct, and the strongest baseline we
test against. Position matching is obviously fragile, so instead you
address each journaled effect by a hash of what the effect actually was:

    key = sha256(order_id | effect_name | amount_cents)

Now a replayed step can only claim a journaled receipt that genuinely
matches it, which fixes the mis-attribution failure in
`replay_position.py`. Teams reach for this pattern precisely because it
looks like it closes the hole.

It trades one failure for another. When the decision diverges on replay,
the content changes, so the key changes, so the journal has no match, so
the effect is issued **again** - and this time the service's own dedupe
cannot save us either, because we handed it a different key.

The lesson is not that content keys are a mistake. It is that any key
derived from a nondeterministic decision inherits that nondeterminism, and
an idempotency key that is not stable is not an idempotency key.
"""

from __future__ import annotations

import hashlib
import os

from belay import chaos
from belay.authz import Denied
from belay.runtimes.base import Ctx, Outcome, Status

NAME = "replay_content"

# See the comment in `_execute`. Default on, i.e. the sound configuration.
JOURNAL_DECISION = os.environ.get("BELAY_JOURNAL_DECISION", "1") == "1"


def content_key(order_id: str, effect: str, amount_cents: int) -> str:
    raw = f"{order_id}|{effect}|{amount_cents}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


class _History:
    """Journaled step results, addressed by content key."""

    def __init__(self, ctx: Ctx):
        self.by_key = {}
        self.steps = {}
        for r in ctx.journal.read():
            if r["kind"] == "step_result":
                if r.get("key"):
                    self.by_key[r["key"]] = r["value"]
                self.steps.setdefault(r["step"], r["value"])

    def effect(self, key: str):
        return self.by_key.get(key)

    def step(self, name: str):
        return self.steps.get(name)


def run(ctx: Ctx) -> Outcome:
    return _execute(ctx, _History(ctx), replaying=False)


def recover(ctx: Ctx) -> Outcome:
    return _execute(ctx, _History(ctx), replaying=True)


def _execute(ctx: Ctx, hist: _History, replaying: bool) -> Outcome:
    j = ctx.journal
    j.append("attempt_start", runtime=NAME, replaying=replaying)

    # Authorisation, journaled as an activity result, as in replay_position.
    if hist.step("authorize") is None:
        try:
            ctx.perms.require("payments:refund")
        except Denied as d:
            j.append("refused", scope=d.scope, at="plan_time")
            return Outcome(Status.REFUSED, notes=[f"denied {d.scope} at plan time"])
        j.append("step_result", step="authorize", key=None, value={"granted": True})

    # The decision.
    #
    # BELAY_JOURNAL_DECISION toggles the one discipline that decides
    # whether this runtime is sound. With it on, the model call is an
    # activity and its result is journaled before it can influence
    # anything, so replay reuses it. With it off, the model call sits in
    # workflow code - which is where people naturally put it, because it
    # reads like orchestration logic - and replay re-invokes it.
    #
    # Nothing in a replay framework detects the difference. The workflow
    # type-checks, passes tests, and behaves identically until a crash
    # lands in the wrong window.
    if not JOURNAL_DECISION:
        plan = ctx.agent.decide(ctx.order_id)
        chaos.maybe_crash("after_decide_before_journal")
        plan_d = plan.as_dict()
        j.observe("inline_decision", plan=plan_d, durable=False,
                  invocation=ctx.agent.invocations)
        diverged_note = "decision made in workflow code; not journaled"
    else:
        cached = hist.step("decide")
        if cached is None:
            plan = ctx.agent.decide(ctx.order_id)
            chaos.maybe_crash("after_decide_before_journal")
            j.append("step_result", step="decide", key=None, value=plan.as_dict())
            plan_d = plan.as_dict()
            diverged_note = "decision taken fresh on this pass"
        else:
            plan_d = cached
            diverged_note = "decision replayed from journal"

    refund_cents = plan_d["refund_cents"]
    credit_cents = plan_d["credit_cents"]

    chaos.maybe_crash("after_intent")

    # The refund, keyed by its own content.
    rkey = content_key(ctx.order_id, "payments.refund", refund_cents)
    if hist.effect(rkey) is None:
        receipt = _issue(ctx, refund_cents, key=rkey)
        chaos.maybe_crash("after_ack_before_record")
        j.append(
            "step_result",
            step="refund",
            key=rkey,
            value={"external_id": receipt.external_id, "amount": receipt.amount_cents},
        )

    chaos.maybe_crash("after_effect_a_recorded")

    if credit_cents:
        ckey = content_key(ctx.order_id, "credits.issue", credit_cents)
        if hist.effect(ckey) is None:
            ctx.credits.issue(ctx.order_id, credit_cents, idem_key=ckey)
            j.append("step_result", step="credit", key=ckey, value={"amount": credit_cents})

    j.append("committed", plan=plan_d)
    return Outcome(
        Status.COMMITTED,
        reported_refund_cents=refund_cents,
        reported_credit_cents=credit_cents,
        plan_label=plan_d["label"],
        notes=[diverged_note],
    )


def _issue(ctx: Ctx, amount: int, key: str):
    if ctx.tier == "idempotent":
        return ctx.payments.refund(ctx.order_id, amount, idem_key=key)
    if ctx.tier == "queryable":
        return ctx.payments.refund(ctx.order_id, amount, client_ref=key)
    return ctx.payments.refund(ctx.order_id, amount)
