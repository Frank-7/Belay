"""The contribution. Anchor effect identity *before* the model decides.

Three rules, and everything else follows from them.

1. **Effect slots are allocated before the decision.**
   A workflow declares its effect slots up front and fsyncs an opaque
   anchor for each. The anchor is the effect's identity. It is not derived
   from the decision, so a diverged decision cannot change it. The model
   chooses the *amount*; it does not get to invent new effect identities.
   An effect with no anchored slot is refused.

2. **Recovery reads; it does not re-derive.**
   On restart we do not replay the workflow to reconstruct what it meant to
   do. The journal is the authoritative record of what was proposed. Every
   anchor with a durable intent and no durable settlement is ambiguous and
   gets reconciled against the service before the workflow moves. The agent
   is only re-invoked when the journal proves that no intent was ever
   written, which means nothing external can have happened.

3. **Ambiguity that the service cannot resolve is escalated, not guessed.**
   On a service offering neither idempotency nor lookup, a lost
   acknowledgement is ambiguous *to this process*. We halt and hand it to a
   human. This costs availability, and we measure that cost rather than
   hiding it.

   The halt is not a dead end. `second/` adjudicates escalated anchors
   against out-of-band records and, when it can verify what happened,
   appends an `adjudicated` record that this projection reads. That package
   is never imported from here and never runs inside recovery; the only
   thing crossing the boundary is a durable journal record carrying the
   provenance of the artefact it came from.

Authorisation is checked live, immediately before each external call, and
is never journaled as a replayable fact.
"""

from __future__ import annotations

import os
import uuid

from belay import chaos
from belay.agent import PLANS
from belay.authz import Denied
from belay.effects import CREDIT, REFUND
from belay.runtimes.base import (
    Ctx,
    Outcome,
    Status,
    Unresolvable,
    resolve_ambiguous_refund,
)

NAME = "anchored"

# Mirrors the toggle in the replay runtimes so that both are handicapped by
# exactly the same developer error. With this off, `anchored` also fails to
# persist the decision - and the experiment shows what that costs here
# versus what it costs a replay runtime.
JOURNAL_DECISION = os.environ.get("BELAY_JOURNAL_DECISION", "1") == "1"

# Rule 1: the effect slots this workflow is permitted to fill, fixed before
# any model output is consulted.
SLOTS = ("refund", "credit")


# --------------------------------------------------------------------------
# Journal projection
# --------------------------------------------------------------------------


class State:
    """What the journal says, with no re-execution of workflow code."""

    def __init__(self, ctx: Ctx):
        self.anchors: dict[str, str] = {}        # slot -> anchor
        self.intents: dict[str, dict] = {}       # slot -> intent record
        self.settled: dict[str, dict] = {}       # slot -> settlement record
        self.plan: dict | None = None
        self.escalated: set[str] = set()   # slots halted, awaiting a human

        for r in ctx.journal.read():
            k = r["kind"]
            if k == "anchor":
                self.anchors[r["slot"]] = r["anchor"]
            elif k == "decided":
                self.plan = r["plan"]
            elif k == "intent":
                self.intents[r["slot"]] = r
            elif k in ("settled", "resolved"):
                self.settled[r["slot"]] = r
            elif k == "escalated":
                self.escalated.add(r.get("slot") or "_workflow")
            elif k == "adjudicated":
                # Written by `second/apply.py` from out-of-band evidence,
                # outside this process and outside the recovery path. It is
                # treated exactly like a `resolved` record, because that is
                # what it is: a *query* result carrying its provenance. The
                # adjudicating agent's conclusion is not what lands here --
                # a verified observation is, along with the digest and
                # source of the artefact it came from. See second/__init__.py
                # for why the import direction never reverses.
                self.escalated.discard(r["slot"])
                if r.get("outcome") in ("committed", "completed"):
                    self.settled[r["slot"]] = r

    def ambiguous_slots(self) -> list[str]:
        return [s for s in self.intents if s not in self.settled]


# --------------------------------------------------------------------------
# Fresh execution
# --------------------------------------------------------------------------


def run(ctx: Ctx) -> Outcome:
    j = ctx.journal
    j.append("attempt_start", runtime=NAME, replaying=False)

    # Rule 1. Anchors first, decision second. Note the ordering: these
    # fsyncs happen before the agent is ever called.
    anchors = {}
    for slot in SLOTS:
        anchors[slot] = uuid.uuid4().hex
        j.append("anchor", slot=slot, anchor=anchors[slot])
    chaos.maybe_crash("after_anchor")

    plan = ctx.agent.decide(ctx.order_id)
    chaos.maybe_crash("after_decide_before_journal")
    if JOURNAL_DECISION:
        j.append("decided", plan=plan.as_dict(), invocation=ctx.agent.invocations)
        return _forward(ctx, State(ctx))

    # Discipline violated: the decision is live only in memory. The anchors
    # are already durable, so no duplicate is possible whatever happens
    # next; the exposure is that a recovering process will not know what
    # else was intended.
    j.observe("inline_decision", plan=plan.as_dict(), durable=False,
              invocation=ctx.agent.invocations)
    st = State(ctx)
    st.plan = plan.as_dict()
    return _forward(ctx, st)


# --------------------------------------------------------------------------
# Recovery
# --------------------------------------------------------------------------


def recover(ctx: Ctx) -> Outcome:
    j = ctx.journal
    st = State(ctx)
    j.append(
        "attempt_start",
        runtime=NAME,
        replaying=True,
        anchors=st.anchors,
        has_decision=st.plan is not None,
        ambiguous=st.ambiguous_slots(),
    )

    if st.escalated:
        return Outcome(
            Status.ESCALATED,
            notes=[f"escalated slots awaiting a human: {sorted(st.escalated)}"],
        )

    missing = [slot for slot in SLOTS if slot not in st.anchors]
    unanchored_effects = [slot for slot in missing
                         if slot in st.intents or slot in st.settled]
    if unanchored_effects:
        j.append("escalated", reason="effect record without a journaled anchor",
                 slots=unanchored_effects)
        return Outcome(Status.ESCALATED, notes=["journal inconsistent; halted"])

    # An anchor is an identity, not an effect. In a valid journal, a slot
    # without an anchor cannot have an intent: intents carry the previously
    # allocated anchor and precede every external call. Thus no effect can
    # exist against the identity minted here. Reject inconsistent evidence
    # above, then finish interrupted allocation before any forward progress.
    # Existing anchors are never re-minted, including after another crash.
    for slot in missing:
        anchor = uuid.uuid4().hex
        j.append("anchor", slot=slot, anchor=anchor, allocation_recovered=True)
        st.anchors[slot] = anchor

    # Rule 2, first half: reconcile everything in flight before moving.
    for slot in st.ambiguous_slots():
        intent = st.intents[slot]
        if slot != "refund":
            # The credit service is idempotent, so re-issuing under the
            # same anchor is safe and needs no ladder.
            continue
        try:
            receipt, method = resolve_ambiguous_refund(
                ctx, intent["anchor"], intent["amount"]
            )
        except Denied as d:
            # The query proved the effect never landed, and we no longer
            # hold the scope needed to complete it. Nothing is in doubt and
            # nothing is owed; we simply stop.
            j.append("refused", scope=d.scope, at="reconciliation",
                     anchor=intent["anchor"], slot=slot)
            return Outcome(
                Status.REFUSED,
                plan_label=(st.plan or {}).get("label"),
                notes=[f"in-flight {slot} never committed; {d.scope} since "
                       "revoked, so it was not completed"],
            )
        except Unresolvable as u:
            # Rule 3. We do not guess about money.
            j.append("escalated", slot=slot, anchor=intent["anchor"], reason=str(u))
            return Outcome(
                Status.ESCALATED,
                plan_label=(st.plan or {}).get("label"),
                notes=[
                    f"slot={slot} anchor={intent['anchor'][:8]} unresolvable: {u}",
                    "halted rather than risk a duplicate irreversible effect",
                ],
            )
        j.append(
            "resolved",
            slot=slot,
            anchor=intent["anchor"],
            method=method,
            external_id=receipt.external_id,
            amount=receipt.amount_cents,
        )
        st = State(ctx)

    # Rule 2, second half: the journaled decision is authoritative. We only
    # re-invoke the agent if no intent was ever durable, which means no
    # external call can have been attempted under any anchor.
    if st.plan is None:
        if st.intents:
            # Cannot happen given the write ordering in `_forward`. If it
            # ever does, the journal is inconsistent and we stop.
            j.append("escalated", reason="intent without a durable decision")
            return Outcome(Status.ESCALATED, notes=["journal inconsistent; halted"])
        plan = ctx.agent.decide(ctx.order_id)
        j.append(
            "decided",
            plan=plan.as_dict(),
            invocation=ctx.agent.invocations,
            note="no durable intent existed, so re-deciding is safe",
        )
        st = State(ctx)
    else:
        # Measure divergence without acting on it. This shadow call exists
        # purely so the experiment can report how often replay *would* have
        # diverged. It never influences control flow.
        shadow = ctx.agent.decide(ctx.order_id)
        j.append(
            "divergence_observed",
            journaled=st.plan["label"],
            shadow=shadow.label,
            diverged=shadow.label != st.plan["label"],
            note="shadow decision recorded for measurement only; not acted on",
        )

    return _forward(ctx, st)


# --------------------------------------------------------------------------
# Shared forward path
# --------------------------------------------------------------------------


def _forward(ctx: Ctx, st: State) -> Outcome:
    """Drive the workflow forward from whatever the journal says.

    Used unchanged by both `run` and `recover`, which is the point: there is
    no separate replay code path to get subtly wrong.
    """
    j = ctx.journal
    plan = PLANS[st.plan["label"]]

    # ---- refund slot ----
    if "refund" not in st.settled:
        anchor = st.anchors["refund"]
        try:
            # Live check, at the instant of use.
            ctx.perms.require(REFUND.scope)
        except Denied as d:
            j.append("refused", scope=d.scope, at="execution_time", anchor=anchor)
            return Outcome(
                Status.REFUSED,
                plan_label=plan.label,
                notes=[f"{d.scope} not held at execution time; no effect issued"],
            )

        j.append(
            "intent",
            slot="refund",
            anchor=anchor,
            effect=REFUND.name,
            amount=plan.refund_cents,
            scope=REFUND.scope,
        )
        chaos.maybe_crash("after_intent")

        receipt = _issue_refund(ctx, plan.refund_cents, anchor)
        chaos.maybe_crash("after_ack_before_record")
        j.append(
            "settled",
            slot="refund",
            anchor=anchor,
            external_id=receipt.external_id,
            amount=receipt.amount_cents,
            deduped=receipt.deduped,
        )
        chaos.maybe_crash("after_effect_a_recorded")

    # ---- credit slot ----
    if plan.credit_cents and "credit" not in st.settled:
        anchor = st.anchors["credit"]
        try:
            ctx.perms.require(CREDIT.scope)
        except Denied as d:
            j.append("refused", scope=d.scope, at="execution_time", anchor=anchor)
            return Outcome(
                Status.REFUSED,
                reported_refund_cents=plan.refund_cents,
                plan_label=plan.label,
                notes=[f"refund settled; {d.scope} not held so credit withheld"],
            )
        j.append(
            "intent",
            slot="credit",
            anchor=anchor,
            effect=CREDIT.name,
            amount=plan.credit_cents,
            scope=CREDIT.scope,
        )
        receipt = ctx.credits.issue(ctx.order_id, plan.credit_cents, idem_key=anchor)
        j.append(
            "settled",
            slot="credit",
            anchor=anchor,
            external_id=receipt.external_id,
            amount=receipt.amount_cents,
        )

    j.append("committed", plan=plan.as_dict())
    return Outcome(
        Status.COMMITTED,
        reported_refund_cents=plan.refund_cents,
        reported_credit_cents=plan.credit_cents,
        plan_label=plan.label,
    )


def _issue_refund(ctx: Ctx, amount: int, anchor: str):
    """The anchor doubles as the idempotency key or client reference,
    whichever the tier accepts. On the opaque tier it is carried anyway so
    that the journal records which anchor the call belonged to."""
    if ctx.tier == "idempotent":
        return ctx.payments.refund(ctx.order_id, amount, idem_key=anchor)
    if ctx.tier == "queryable":
        return ctx.payments.refund(ctx.order_id, amount, client_ref=anchor)
    return ctx.payments.refund(ctx.order_id, amount)
