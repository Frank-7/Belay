"""Turning a validated dossier into a durable fact.

Collaborators are injected rather than imported. `apply_dossier` needs a
journal, a permission store, and a way to issue the effect; it does not need
-- and must not have -- the ledger. Wiring happens in `experiments/`, which
is grader-side and allowed to see the oracle.

Four things here are load-bearing.

**A dossier resolves the journal state it inspected.** Immediately before
applying either rung, the live slot must still be halted with the same
anchor, amount, scope and journal revision. A completed slot or a newer
attempt invalidates the dossier, even if the newer attempt raised before
recording its outcome. Only fresh adjudication may resolve that uncertainty.
This check assumes one workflow instance at a time, as in CONTRACT.md; it
is not a lease and does not permit concurrent writers of the same journal.

**Authorisation happens at execution, not at proposal.** I2 says the
permission check and the call must not be separated by a restart. A dossier
may sit in a queue for an hour while a human reads it, so it cannot carry an
authorisation with it. `perms.require` is called here, microseconds before
the effect, and a revoked scope means the anchor stays halted -- which was
already an acceptable outcome.

**A query needs no permission; a completion does.** Reporting what
out-of-band records already show creates nothing. Issuing the effect because
evidence proved it never landed is a new effect. Collapsing the two is the
bug in FINDINGS.md S6 and the enum in `dossier.py` exists so it cannot be
collapsed by accident here.

**The adjudicator anchors its own effect before issuing it.** A completion
writes `adjudication_intent` and fsyncs *before* calling the service, for
precisely the reason `anchored.py` writes an intent first: if this process
dies in the window, a later adjudication must know that a call was attempted
at that moment, or it will read a stale settlement report, see silence, and
conclude absence a second time. `escalated_slots` folds that timestamp into
the coverage requirement. The tool built to close the escalation hole is
subject to the same discipline as the runtime it serves, which is either
pleasing or embarrassing depending on how long it took to notice.
"""

from __future__ import annotations

from dataclasses import dataclass

from belay.authz import Denied
from second.adjudicate import project_escalated_slots
from second.dossier import Dossier, ProposalKind, Verdict

# What happened. Reported by the experiment, and written to the journal.
NONE = "none"                           # abstained; the anchor stays halted
CLOSED_FROM_EVIDENCE = "closed_from_evidence"   # query rung; no effect issued
COMPLETED = "completed"                 # completion rung; a new effect issued
REFUSED = "refused"                     # scope gone at execution time
INCONSISTENT = "inconsistent"           # stale state or inconsistent dossier shape


@dataclass
class Applied:
    action: str
    note: str
    dossier: Dossier
    external_id: int | None = None

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "note": self.note,
            "external_id": self.external_id,
            "dossier": self.dossier.as_dict(),
        }


def _citation_summary(dossier: Dossier) -> list[dict]:
    """Provenance, not prose. What gets journaled is where the evidence came
    from and its digest -- never the agent's summary of it."""
    return [
        {
            "pointer": c["pointer"],
            "digest": c["digest"],
            "provenance": c["provenance"],
        }
        for c in dossier.citations
    ]


def apply_dossier(
    dossier: Dossier,
    *,
    journal,
    perms,
    issue_effect=None,
    operator: str = "unattributed",
) -> Applied:
    """Apply one dossier under the single-workflow-instance assumption.

    `issue_effect(amount_cents) -> receipt` is required only for a
    completion. The receipt needs `external_id` and `amount_cents`.
    I/O and effect exceptions propagate. Once an adjudication intent is
    durable, even an exception leaves an ambiguous attempt that requires
    fresh adjudication; replaying this dossier will be refused.
    """
    d = dossier

    # ---- abstention: audit trail only ------------------------------------
    if d.verdict is Verdict.ABSTAIN:
        # Recorded so the human can see an attempt was made and why it
        # failed. `anchored.py` does not project this kind, so it cannot
        # clear the halt -- an abstention is inert by construction.
        journal.append(
            "adjudication_abstained",
            slot=d.slot,
            anchor=d.anchor,
            why=d.validator_notes,
            pointers_proposed=d.pointers_proposed,
            pointers_resolved=d.pointers_resolved,
            operator=operator,
        )
        return Applied(NONE, "; ".join(d.validator_notes) or "abstained", d)

    # Check state for both rungs. Querying creates nothing, but a stale query
    # must not overwrite a newer completion or resolve a different intent.
    live = next(
        (s for s in project_escalated_slots(journal.read(), "") if s.slot == d.slot),
        None,
    )
    if live is None:
        return Applied(INCONSISTENT, "slot is not currently halted and unresolved", d)
    if not d.journal_revision or d.journal_revision != live.journal_revision:
        return Applied(INCONSISTENT, "journal state changed or dossier is unbound; "
                       "adjudicate the current slot again", d)
    if d.anchor != live.anchor or d.amount_cents != live.amount_cents:
        return Applied(INCONSISTENT, "dossier identity or amount differs from live intent", d)
    if d.proposal.amount_cents != live.amount_cents:
        return Applied(INCONSISTENT, "proposal amount differs from live intent", d)

    # ---- query rung: evidence already settles it -------------------------
    if d.verdict is Verdict.COMMITTED:
        if d.proposal.kind is not ProposalKind.QUERY:
            return Applied(INCONSISTENT, "committed verdict with a non-query proposal", d)
        if d.proposal.scope is not None:
            return Applied(INCONSISTENT, "query proposal unexpectedly carries a scope", d)
        journal.append(
            "adjudicated",
            slot=d.slot,
            anchor=d.anchor,
            outcome="committed",
            method="evidence_query",
            amount=d.amount_cents,
            external_id=d.external_id,
            citations=_citation_summary(d),
            journal_revision=d.journal_revision,
            validator_notes=d.validator_notes,
            operator=operator,
            note="out-of-band records show the effect committed; no effect issued",
        )
        return Applied(
            CLOSED_FROM_EVIDENCE,
            f"evidence shows {d.amount_cents}c already committed",
            d,
            external_id=d.external_id,
        )

    # ---- completion rung: a new effect, so a live check ------------------
    if d.verdict is Verdict.ABSENT:
        if d.proposal.kind is not ProposalKind.COMPLETION:
            return Applied(INCONSISTENT, "absent verdict with a non-completion proposal", d)
        if issue_effect is None:
            return Applied(INCONSISTENT, "completion proposed with no effect issuer wired", d)
        scope = d.proposal.scope
        amount = d.proposal.amount_cents
        if not scope or amount is None:
            return Applied(INCONSISTENT, "completion missing scope or amount", d)
        if scope != live.scope:
            return Applied(INCONSISTENT, "proposal scope differs from live intent", d)

        try:
            perms.require(scope)
        except Denied as denied:
            journal.append(
                "adjudication_refused",
                slot=d.slot,
                anchor=d.anchor,
                scope=denied.scope,
                at="adjudication_execution_time",
                citations=_citation_summary(d),
                operator=operator,
                note="evidence proved the effect never landed, but the scope "
                     "needed to complete it is no longer held",
            )
            return Applied(REFUSED, f"{denied.scope} not held at execution time", d)

        # Anchor before acting. See the module docstring: this fsync is what
        # stops a second adjudication from misreading a stale report.
        journal.append(
            "adjudication_intent",
            slot=d.slot,
            anchor=d.anchor,
            amount=amount,
            scope=scope,
            citations=_citation_summary(d),
            journal_revision=d.journal_revision,
            operator=operator,
        )

        receipt = issue_effect(amount)

        journal.append(
            "adjudicated",
            slot=d.slot,
            anchor=d.anchor,
            outcome="completed",
            method="evidence_absent_then_completed",
            amount=int(receipt.amount_cents),
            external_id=int(receipt.external_id),
            citations=_citation_summary(d),
            journal_revision=d.journal_revision,
            validator_notes=d.validator_notes,
            operator=operator,
            note="evidence proved the effect never landed; completed under a "
                 "live permission check",
        )
        return Applied(
            COMPLETED,
            f"evidence proved absent; issued {receipt.amount_cents}c",
            d,
            external_id=int(receipt.external_id),
        )

    return Applied(INCONSISTENT, f"unhandled verdict {d.verdict!r}", d)
