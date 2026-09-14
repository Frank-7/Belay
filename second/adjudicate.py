"""The pipeline, and the validator that is the real trust boundary.

Shape of one adjudication:

    journal ──▶ EscalatedSlot ──▶ agent proposes pointers
                                        │
                            EvidenceStore.fetch  (deterministic)
                                        │
                              verified observations only
                                        │
                                 agent concludes
                                        │
                                   validate()      ◀── the trust boundary
                                        │
                                    Dossier

The agent appears twice and owns nothing either time. It says where to look,
and it says committed / absent / abstain. Everything load-bearing --
whether a pointer resolved, whether a citation is real, whether the cited
evidence actually supports the verdict, what the amount is, which scope is
required -- is decided here, deterministically, from the journal and the
fetched artefacts.

`validate` has exactly one failure mode: it returns an abstention. It does
not raise and it does not repair. That is what makes a bad agent merely
useless rather than dangerous, and it is the property the experiment
measures by deliberately degrading the agent.

**A stated assumption.** On the `opaque` tier the service never received a
caller key, so out-of-band records cannot be matched to an anchor -- only to
an order. This workflow has one refund slot per order, so "a refund for this
order, for this amount" identifies the slot. A workflow with two refund
slots on one order would need the amounts to differ, or would need an
evidence source that carries the client reference, which is to say it would
need the service to have been `queryable` after all. We do not paper over
this: the guard below requires the amount to match the journaled intent, and
anything else abstains.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from itertools import islice

from belay.journal import Journal  # reads only; imports no ledger
from second.dossier import Claim, Dossier, Proposal, ProposalKind, Verdict
from second.evidence import (
    MAX_AGENT_POINTERS,
    MAX_CONTEXT_SOURCES,
    SEL_MANIFEST,
    SEL_ORDER,
    Coverage,
    EvidenceStore,
    Observation,
    Pointer,
)


@dataclass(frozen=True)
class EscalatedSlot:
    """One halted anchor, as the journal describes it.

    Everything the adjudicator treats as fact comes from this object. The
    agent is shown it but cannot alter it.
    """

    anchor: str
    slot: str
    order_id: str
    amount_cents: int
    scope: str
    intent_ts: float
    reason: str
    journal_revision: str | None = None

    def view(self, catalog: list[str]) -> dict:
        """What the agent is allowed to see. Deliberately not the ledger,
        and deliberately not the contents of any evidence source -- only
        which sources exist, so it has to ask."""
        return {
            "anchor": self.anchor,
            "slot": self.slot,
            "order_id": self.order_id,
            "amount_cents": self.amount_cents,
            "intent_ts": self.intent_ts,
            "escalation_reason": self.reason,
            "evidence_sources_available": list(catalog),
        }


def escalated_slots(run_dir: str, order_id: str) -> list[EscalatedSlot]:
    """Project the journal for anchors that are halted and not yet adjudicated.

    This is a read of the same durable records `anchored.py` projects, with
    no re-execution of workflow code -- rule 2, applied from outside the
    process.
    """
    path = os.path.join(run_dir, "journal.jsonl")
    if not os.path.exists(path):
        return []
    return project_escalated_slots(Journal(path, "adjudicator-read").read(), order_id)


def project_escalated_slots(records: list[dict], order_id: str) -> list[EscalatedSlot]:
    """Project a supplied journal snapshot, including each slot's revision.

    Bind to all records that can change this slot's identity, intent, attempt
    window or outcome. Audit records and records for other slots do not
    invalidate an otherwise current proposal. A timestamp alone is not a
    revision: two attempts can have the same clock reading.
    """

    anchors: dict[str, str] = {}
    intents: dict[str, dict] = {}
    halted: dict[str, dict] = {}
    closed: set[str] = set()
    attempted_at: dict[str, float] = {}
    relevant: dict[str, list[dict]] = {}
    for r in records:
        kind = r.get("kind")
        slot = r.get("slot")
        if slot and kind in {
            "anchor", "intent", "escalated", "adjudication_intent",
            "settled", "resolved", "adjudicated",
        }:
            relevant.setdefault(slot, []).append(r)
        if kind == "anchor" and slot:
            anchors[slot] = r["anchor"]
        elif kind == "intent" and slot:
            intents[slot] = r
        elif kind == "escalated" and slot:
            halted[slot] = r
        elif kind in ("settled", "resolved", "adjudicated") and slot:
            closed.add(slot)
        elif kind == "adjudication_intent" and slot:
            # A previous adjudication was about to issue this effect and may
            # have died in the window. Its timestamp widens the window that
            # an evidence source must cover before its silence means
            # anything -- see `second/apply.py`.
            attempted_at[slot] = max(attempted_at.get(slot, 0.0), float(r["ts"]))

    out: list[EscalatedSlot] = []
    for slot, esc in halted.items():
        if slot in closed:
            continue
        intent = intents.get(slot)
        if intent is None:
            # Halted without a durable intent. Nothing external can have
            # been attempted, so there is nothing to adjudicate.
            continue
        if esc.get("anchor") != intent.get("anchor"):
            continue
        if slot in anchors and anchors[slot] != intent.get("anchor"):
            continue
        out.append(
            EscalatedSlot(
                anchor=intent["anchor"],
                slot=slot,
                order_id=order_id,
                amount_cents=int(intent["amount"]),
                scope=intent["scope"],
                # The latest moment at which a call may have been attempted,
                # counting earlier adjudications as well as the workflow.
                intent_ts=max(float(intent["ts"]), attempted_at.get(slot, 0.0)),
                reason=str(esc.get("reason", "")),
                journal_revision=hashlib.sha256(
                    json.dumps(relevant[slot], sort_keys=True, separators=(",", ":"))
                    .encode("utf-8")
                ).hexdigest(),
            )
        )
    return out


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------


def adjudicate(esc: EscalatedSlot, store: EvidenceStore, agent) -> Dossier:
    """Run one adjudication. Never raises; a bad agent yields an abstention."""
    catalog = store.catalog()
    if len(catalog) > MAX_CONTEXT_SOURCES:
        return Dossier.abstain(esc.anchor, esc.slot, "evidence context exceeds the 8-source safety budget; narrow the case before adjudicating")
    view = esc.view(catalog)

    # Round 1: where to look. Raw strings, straight from the model.
    try:
        raw_pointers = list(islice(agent.propose_pointers(view) or [], MAX_AGENT_POINTERS + 1))
    except Exception as exc:  # a model wrapper may fail in any way at all
        return Dossier.abstain(esc.anchor, esc.slot, f"agent failed proposing: {exc!r}")
    if len(raw_pointers) > MAX_AGENT_POINTERS:
        return Dossier.abstain(
            esc.anchor, esc.slot, "agent exceeded the 16-pointer budget",
            pointers_proposed=len(raw_pointers),
        )

    # Deterministic fetch. Unparseable and unresolvable pointers vanish
    # here, which is why a fabricated one is inert rather than harmful.
    observations: list[Observation] = []
    seen: set[str] = set()
    for raw in raw_pointers[:MAX_AGENT_POINTERS]:
        obs = store.fetch(Pointer.parse(raw))
        if obs is None or obs.digest in seen:
            continue
        seen.add(obs.digest)
        observations.append(obs)

    # A model may overlook or selectively omit a source. Read the bounded
    # catalog's exact order queries and manifests for a deterministic veto.
    # These extra observations cannot provide missing citations or upgrade the
    # model's conclusion; the model still has to request and cite its support.
    fetched = {str(obs.pointer): obs for obs in observations}
    context: list[Observation] = []
    for source in catalog:
        for selector in (SEL_MANIFEST, f"{SEL_ORDER}:{esc.order_id}"):
            pointer = Pointer(source, selector)
            obs = fetched.get(str(pointer)) or store.fetch(pointer)
            if obs is None:
                return Dossier.abstain(
                    esc.anchor, esc.slot,
                    f"available source {source!r} could not be read safely; obtain a valid source snapshot",
                    pointers_proposed=len(raw_pointers), pointers_resolved=len(observations),
                )
            context.append(obs)

    # Round 2: conclude, over verified observations only.
    try:
        claim = agent.conclude(view, observations)
    except Exception as exc:
        return Dossier.abstain(
            esc.anchor, esc.slot, f"agent failed concluding: {exc!r}",
            pointers_proposed=len(raw_pointers), pointers_resolved=len(observations),
        )
    if not isinstance(claim, Claim):
        return Dossier.abstain(
            esc.anchor, esc.slot, "agent returned a non-Claim object",
            pointers_proposed=len(raw_pointers), pointers_resolved=len(observations),
        )

    return validate(
        esc, claim, observations,
        pointers_proposed=len(raw_pointers),
        pointers_resolved=len(observations),
        context_observations=context,
    )


# --------------------------------------------------------------------------
# The validator
# --------------------------------------------------------------------------


def validate(
    esc: EscalatedSlot,
    claim: Claim,
    observations: list[Observation],
    *,
    pointers_proposed: int = 0,
    pointers_resolved: int = 0,
    context_observations: list[Observation] | None = None,
) -> Dossier:
    """Fail closed even on malformed claims or manually supplied observations.

    Context is trusted fetcher output used only to reject a claim. It cannot
    satisfy a citation the agent did not request. Direct callers must supply
    the full bounded context; production callers should use ``adjudicate``.
    """
    try:
        return _validate(
            esc, claim, observations, pointers_proposed=pointers_proposed,
            pointers_resolved=pointers_resolved, context_observations=context_observations,
        )
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        return Dossier.abstain(
            esc.anchor, esc.slot, "malformed claim or evidence; obtain a valid source snapshot",
            pointers_proposed=pointers_proposed, pointers_resolved=pointers_resolved,
        )


def _context_problem(esc: EscalatedSlot, observations: list[Observation]) -> str | None:
    """Conservative consistency check under the one-refund-slot assumption.

    Local file provenance and declared coverage are assumed truthful. This is
    conflict detection, not Byzantine consensus or provider finality proof.
    """
    manifests: dict[str, Observation] = {}
    silent: set[str] = set()
    hits: list[dict] = []
    identities: set[int] = set()
    transactions_by_chain: dict[int, set[str]] = {}
    snapshots: dict[str, str] = {}
    for obs in observations:
        source = obs.pointer.source
        if obs.payload.get("source") != source:
            return "source identity disagrees with the fetched pointer"
        previous = snapshots.setdefault(str(obs.pointer), obs.digest)
        if previous != obs.digest:
            return "source changed within the evidence snapshot; fetch a consistent snapshot"
        if obs.pointer.selector == SEL_MANIFEST:
            if not isinstance(obs.payload.get("coverage"), dict):
                return "malformed source coverage; obtain a valid manifest"
            manifests[source] = obs
            continue
        if obs.payload.get("selector") != obs.pointer.selector:
            return "query selector disagrees with its fetched pointer"
        records = obs.payload.get("matches")
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            return "malformed evidence records; obtain a valid source snapshot"
        if obs.pointer.kind == SEL_ORDER and any(rec.get("order_id") != obs.pointer.arg for rec in records):
            return "query returned evidence for a different order"
        if obs.pointer.selector != f"{SEL_ORDER}:{esc.order_id}":
            continue
        if not records:
            silent.add(source)
        for rec in records:
            if rec.get("order_id") != esc.order_id:
                return "query returned evidence for a different order"
            if rec.get("kind") not in (None, "refund"):
                continue
            if type(rec.get("amount_cents")) is not int or rec["amount_cents"] < 0:
                return "malformed refund amount; obtain a valid source snapshot"
            if rec["amount_cents"] != esc.amount_cents:
                return "conflicting refund amount for this order; reconcile the slot identity before acting"
            external_id = rec.get("external_id")
            if external_id is not None:
                if type(external_id) is not int or external_id < 0:
                    return "malformed simulator effect identity; transaction hashes belong in receipt metadata"
                identities.add(external_id)
            metadata = rec.get("metadata") or {}
            if not isinstance(metadata, dict):
                return "malformed receipt metadata; obtain a valid source snapshot"
            tx_hash = rec.get("transaction_hash", metadata.get("transaction_hash"))
            chain_id = rec.get("chain_id", metadata.get("chain_id"))
            if tx_hash is not None:
                if not isinstance(tx_hash, str) or re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash) is None:
                    return "malformed transaction hash in receipt metadata"
                if chain_id is not None:
                    if type(chain_id) is not int or chain_id <= 0:
                        return "malformed chain identity in receipt metadata"
                    transactions_by_chain.setdefault(chain_id, set()).add(tx_hash.lower())
            hits.append(rec)
    if len(identities) > 1:
        return "conflicting effect identities for one refund slot; reconcile possible duplicate effects"
    if any(len(hashes) > 1 for hashes in transactions_by_chain.values()):
        return "conflicting transaction hashes for one refund slot on the same chain; reconcile possible duplicate transfers"
    if hits:
        for source in silent:
            manifest = manifests.get(source)
            if manifest and Coverage.from_dict(manifest.payload["coverage"]).proves_absence_at(esc.intent_ts):
                return "conflicting sources: a matching commit and a complete silent source; reconcile their coverage and event identity"
    return None


def _validate(
    esc: EscalatedSlot,
    claim: Claim,
    observations: list[Observation],
    *,
    pointers_proposed: int = 0,
    pointers_resolved: int = 0,
    context_observations: list[Observation] | None = None,
) -> Dossier:
    """Decide whether the claim is supported by evidence actually fetched.

    Deterministic validation over typed claims and observations. The public
    wrapper also turns malformed input into an abstention.
    """
    notes: list[str] = []
    counts = {"pointers_proposed": pointers_proposed, "pointers_resolved": pointers_resolved}

    def give_up(why: str, cited: list[Observation] | None = None) -> Dossier:
        return Dossier.abstain(
            esc.anchor, esc.slot, why,
            reasoning=claim.reasoning,
            citations=[o.as_dict() for o in (cited or [])],
            **counts,
        )

    problem = _context_problem(esc, observations + (context_observations or []))
    if problem:
        return give_up(problem, observations + (context_observations or []))

    # -- citations must name observations this adjudication really fetched --
    by_digest = {o.digest: o for o in observations}
    cited: list[Observation] = []
    for c in claim.citations:
        obs = by_digest.get(c) if isinstance(c, str) else None
        if obs is None:
            # A digest we never produced. Recorded for the human, then
            # dropped. It cannot support anything.
            notes.append(f"citation {str(c)[:16]!r} matches no fetched observation")
            continue
        cited.append(obs)

    try:
        verdict = Verdict(claim.verdict)
    except ValueError:
        return give_up(f"unrecognised verdict {claim.verdict!r}", cited)

    if verdict is Verdict.ABSTAIN:
        return give_up("agent abstained", cited)

    if not cited:
        return give_up(f"verdict {verdict.value!r} with no verifiable citation", cited)

    # -- COMMITTED: one matching source, with no contextual contradiction ---
    if verdict is Verdict.COMMITTED:
        for obs in cited:
            for rec in obs.matches:
                if rec.get("kind") not in (None, "refund"):
                    continue
                if rec.get("order_id") != esc.order_id:
                    continue
                if type(rec.get("amount_cents")) is not int or rec["amount_cents"] != esc.amount_cents:
                    # A refund for this order at a different amount is not
                    # this slot. See the assumption in the module docstring.
                    notes.append(
                        f"ignored {obs.pointer} match at "
                        f"{rec.get('amount_cents')}c != intent {esc.amount_cents}c"
                    )
                    continue
                ext = rec.get("external_id")
                return Dossier(
                    anchor=esc.anchor,
                    slot=esc.slot,
                    journal_revision=esc.journal_revision,
                    verdict=Verdict.COMMITTED,
                    # Reporting what already happened creates nothing, so
                    # this rung needs no permission.
                    proposal=Proposal(ProposalKind.QUERY, amount_cents=esc.amount_cents),
                    amount_cents=esc.amount_cents,
                    external_id=ext,
                    citations=[obs.as_dict()],
                    reasoning=claim.reasoning,
                    validator_notes=notes + [
                        f"{obs.pointer} shows a {esc.amount_cents}c refund "
                        f"for {esc.order_id}; provenance {obs.provenance}"
                    ],
                    **counts,
                )
        return give_up("no cited observation shows a matching committed effect", cited)

    # -- ABSENT: needs coverage, not just silence --------------------------
    # A matching positive observation cannot be concealed by citing only a
    # silent source whose coverage is old or missing.
    for obs in observations + (context_observations or []):
        if any(
            rec.get("kind") in (None, "refund") and rec.get("order_id") == esc.order_id
            and rec.get("amount_cents") == esc.amount_cents for rec in obs.matches
        ):
            return give_up("absence contradicted by an available matching committed effect", [obs])
    # Silence from a lossy source proves nothing at any drop rate, so the
    # agent must cite a manifest claiming completeness over the intent
    # window *and* the silent query from that same source.
    # source -> the silent order query cited for it. Bound by identity rather
    # than looked up again later, so the observation the dossier cites is
    # exactly the one whose silence was checked.
    silent_by_source: dict[str, Observation] = {}
    expected_selector = f"{SEL_ORDER}:{esc.order_id}"
    for o in cited:
        if (
            o.pointer.selector == expected_selector
            and o.payload.get("selector") == expected_selector
            and not o.matches
        ):
            silent_by_source.setdefault(str(o.payload.get("source")), o)
    for obs in cited:
        if obs.pointer.kind != SEL_MANIFEST:
            continue
        source = str(obs.payload.get("source"))
        silent = silent_by_source.get(source)
        if silent is None:
            continue
        cov_raw = obs.payload.get("coverage") or {}
        cov = Coverage.from_dict(cov_raw)
        if not cov.proves_absence_at(esc.intent_ts):
            notes.append(
                f"{source} coverage {cov.kind}"
                + (f" (cutoff {cov.cutoff_ts})" if cov.cutoff_ts else "")
                + f" cannot rule out an event at {esc.intent_ts}"
            )
            continue
        return Dossier(
            anchor=esc.anchor,
            slot=esc.slot,
            journal_revision=esc.journal_revision,
            verdict=Verdict.ABSENT,
            # Completing it is a *new* external effect. Scope and amount
            # come from the journaled intent, never from the agent.
            proposal=Proposal(
                ProposalKind.COMPLETION,
                scope=esc.scope,
                amount_cents=esc.amount_cents,
            ),
            amount_cents=esc.amount_cents,
            citations=[obs.as_dict(), silent.as_dict()],
            reasoning=claim.reasoning,
            validator_notes=notes + [
                f"{source} is complete through {cov.cutoff_ts} and holds no "
                f"refund for {esc.order_id}; intent at {esc.intent_ts} is covered"
            ],
            **counts,
        )

    return give_up(
        "absence not established: no cited source claims completeness over "
        "the intent window while also being silent",
        cited,
    )


# --------------------------------------------------------------------------
# The control
# --------------------------------------------------------------------------


def adjudicate_trusting(esc: EscalatedSlot, store: EvidenceStore, agent) -> Dossier:
    """The same pipeline with the validator removed. **A baseline, not an API.**

    This exists for the same reason `belay/runtimes/naive.py` exists: a
    guarantee that is never contrasted with its absence is not a measured
    guarantee. "Zero false resolutions" means nothing until you can say what
    the same agent, on the same evidence, does when believed.

    And it is not a strawman. This is the obvious implementation -- give a
    model the escalation queue and some log access, do what it concludes.
    The agent still cannot name an amount or a scope here, because the
    `Claim` schema does not carry them; the *only* thing withdrawn is
    `validate`. So the delta the experiment reports is attributable to
    verification alone, not to the schema.

    Nothing outside `experiments/run_adjudication.py` should call this.
    """
    view = esc.view(store.catalog())
    try:
        raw_pointers = list(agent.propose_pointers(view) or [])
        observations: list[Observation] = []
        for raw in raw_pointers[:16]:
            obs = store.fetch(Pointer.parse(raw))
            if obs is not None:
                observations.append(obs)
        claim = agent.conclude(view, observations)
    except Exception as exc:
        return Dossier.abstain(esc.anchor, esc.slot, f"agent failed: {exc!r}")

    counts = {
        "pointers_proposed": len(raw_pointers),
        "pointers_resolved": len(observations),
    }
    cited = [o.as_dict() for o in observations]

    if claim.verdict == Verdict.COMMITTED.value:
        return Dossier(
            anchor=esc.anchor, slot=esc.slot, verdict=Verdict.COMMITTED,
            journal_revision=esc.journal_revision,
            proposal=Proposal(ProposalKind.QUERY, amount_cents=esc.amount_cents),
            amount_cents=esc.amount_cents, citations=cited,
            reasoning=claim.reasoning,
            validator_notes=["UNVALIDATED: took the agent's word"], **counts,
        )
    if claim.verdict == Verdict.ABSENT.value:
        return Dossier(
            anchor=esc.anchor, slot=esc.slot, verdict=Verdict.ABSENT,
            journal_revision=esc.journal_revision,
            proposal=Proposal(
                ProposalKind.COMPLETION, scope=esc.scope,
                amount_cents=esc.amount_cents,
            ),
            amount_cents=esc.amount_cents, citations=cited,
            reasoning=claim.reasoning,
            validator_notes=["UNVALIDATED: took the agent's word"], **counts,
        )
    return Dossier.abstain(
        esc.anchor, esc.slot, "agent abstained", reasoning=claim.reasoning, **counts
    )
