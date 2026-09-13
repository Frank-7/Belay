#!/usr/bin/env python3
"""Assertions on the adjudicator's safety properties.

Same stance as `tests/test_contract.py`: these are not unit tests of helper
functions, they are the claims `second/` makes, asserted directly. The
governing one is that a *wrong* resolution must be impossible even when the
agent is actively bad, because the halt it replaces was already an honest
outcome under CONTRACT.md I3.

    python3 tests/test_second.py
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import sys
import tempfile
from dataclasses import replace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.authz import PermissionStore  # noqa: E402
from belay.journal import Journal  # noqa: E402
from second import apply as second_apply  # noqa: E402
from second.adjudicate import (  # noqa: E402
    EscalatedSlot,
    adjudicate_trusting,
    escalated_slots,
    validate,
)
from second.dossier import Claim, ProposalKind, Verdict  # noqa: E402
from second.evidence import EvidenceStore, Pointer  # noqa: E402

ORDER = "order-test"
AMOUNT = 5000
INTENT_TS = 1_000_000.0

_passed = 0
_failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  pass  {name}")
    else:
        _failed.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _slot() -> EscalatedSlot:
    return EscalatedSlot(
        anchor="a" * 32,
        slot="refund",
        order_id=ORDER,
        amount_cents=AMOUNT,
        scope="payments:refund",
        intent_ts=INTENT_TS,
        reason="opaque tier offers no post-hoc lookup",
    )


def _evidence(base: str, name: str, coverage: dict, records: list[dict]) -> EvidenceStore:
    d = os.path.join(base, f"ev-{name}-{random.randint(0, 1 << 30)}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{name}.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": name, "coverage": coverage, "records": records}, fh)
    return EvidenceStore(d)


def _refund_record(amount: int = AMOUNT, ts: float = INTENT_TS + 0.5) -> dict:
    return {
        "service": "payments",
        "kind": "refund",
        "order_id": ORDER,
        "amount_cents": amount,
        "external_id": 1,
        "ts": ts,
        "anchor": None,
    }


COMPLETE = {"kind": "complete_until", "cutoff_ts": INTENT_TS + 100, "note": ""}
STALE = {"kind": "complete_until", "cutoff_ts": INTENT_TS - 1, "note": ""}
LOSSY = {"kind": "lossy", "drop_rate": 0.35, "note": ""}


def _fetch_all(store: EvidenceStore, source: str) -> list:
    return [
        o for o in (
            store.fetch(Pointer.parse(f"{source}:manifest")),
            store.fetch(Pointer.parse(f"{source}:order:{ORDER}")),
        ) if o is not None
    ]


# --------------------------------------------------------------------------
# The import direction is the guarantee
# --------------------------------------------------------------------------


def test_import_direction() -> None:
    print("\nthe import direction is the architectural guarantee")

    offenders = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "belay")):
        for f in files:
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(dirpath, f), encoding="utf-8").read()
            # Comments and docstrings may name it; imports may not.
            if re.search(r"^\s*(?:from|import)\s+second\b", src, re.M):
                offenders.append(os.path.join(dirpath, f))
    check(
        "nothing under belay/ imports second/",
        not offenders,
        f"offenders={offenders}",
    )

    offenders = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "second")):
        for f in files:
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(dirpath, f), encoding="utf-8").read()
            if re.search(r"^\s*(?:from|import)\s+services\b", src, re.M):
                offenders.append(os.path.join(dirpath, f))
    check(
        "nothing under second/ imports the ledger",
        not offenders,
        f"offenders={offenders}",
    )


# --------------------------------------------------------------------------
# A fabricated pointer is inert
# --------------------------------------------------------------------------


def test_pointers_must_resolve(base: str) -> None:
    print("\na pointer the fetcher cannot resolve yields no observation")
    store = _evidence(base, "settlement", COMPLETE, [_refund_record()])

    check("unknown source resolves to nothing",
          store.fetch(Pointer.parse(f"processor_dashboard:order:{ORDER}")) is None)
    check("malformed pointer resolves to nothing",
          store.fetch(Pointer.parse("this is not a pointer")) is None)
    check("unknown selector resolves to nothing",
          store.fetch(Pointer.parse("settlement:invoices")) is None)
    check(
        "anchor selector is declined when records carry no caller key",
        store.fetch(Pointer.parse("settlement:anchor:" + "a" * 32)) is None,
        "an opaque service received no key, so the question is unanswerable",
    )
    check("a real pointer resolves",
          store.fetch(Pointer.parse(f"settlement:order:{ORDER}")) is not None)


# --------------------------------------------------------------------------
# The validator
# --------------------------------------------------------------------------


def test_citations_must_be_real(base: str) -> None:
    print("\na verdict needs a citation the adjudication actually fetched")
    store = _evidence(base, "settlement", COMPLETE, [_refund_record()])
    obs = _fetch_all(store, "settlement")

    d = validate(_slot(), Claim(verdict="committed", citations=["0" * 16]), obs)
    check("fabricated digest cannot support a verdict",
          d.verdict is Verdict.ABSTAIN, f"got {d.verdict}")

    d = validate(_slot(), Claim(verdict="committed", citations=[]), obs)
    check("no citation at all cannot support a verdict",
          d.verdict is Verdict.ABSTAIN, f"got {d.verdict}")

    d = validate(_slot(), Claim(verdict="fabulous", citations=[obs[0].digest]), obs)
    check("an unrecognised verdict abstains",
          d.verdict is Verdict.ABSTAIN, f"got {d.verdict}")


def test_absence_needs_coverage_not_silence(base: str) -> None:
    print("\nsilence proves absence only from a source that covers the window")

    # Lossy source, silent. A hit would be proof; silence is worth nothing.
    store = _evidence(base, "webhook", LOSSY, [])
    obs = _fetch_all(store, "webhook")
    d = validate(
        _slot(),
        Claim(verdict="absent", citations=[o.digest for o in obs]),
        obs,
    )
    check("lossy silence never proves absence",
          d.verdict is Verdict.ABSTAIN, f"got {d.verdict}")

    # Complete, but its cutoff stops before the intent.
    store = _evidence(base, "settlement", STALE, [])
    obs = _fetch_all(store, "settlement")
    d = validate(
        _slot(),
        Claim(verdict="absent", citations=[o.digest for o in obs]),
        obs,
    )
    check("silence outside the covered window never proves absence",
          d.verdict is Verdict.ABSTAIN, f"got {d.verdict}")

    # Complete and covering. Now silence means something.
    store = _evidence(base, "settlement", COMPLETE, [])
    obs = _fetch_all(store, "settlement")
    d = validate(
        _slot(),
        Claim(verdict="absent", citations=[o.digest for o in obs]),
        obs,
    )
    check("covering silence does prove absence",
          d.verdict is Verdict.ABSENT, f"got {d.verdict}")
    check("and absence proposes a completion, which needs authorisation",
          d.proposal.kind is ProposalKind.COMPLETION and d.proposal.requires_authz)
    check("with the amount taken from the journal, not the agent",
          d.proposal.amount_cents == AMOUNT, f"got {d.proposal.amount_cents}")


def test_commitment_needs_a_matching_record(base: str) -> None:
    print("\ncommitment needs a record matching the journaled intent")

    store = _evidence(base, "settlement", COMPLETE, [_refund_record()])
    obs = _fetch_all(store, "settlement")
    d = validate(
        _slot(), Claim(verdict="committed", citations=[o.digest for o in obs]), obs
    )
    check("a matching hit proves commitment",
          d.verdict is Verdict.COMMITTED, f"got {d.verdict}")
    check("and proposes a query, which needs no authorisation",
          d.proposal.kind is ProposalKind.QUERY and not d.proposal.requires_authz)

    # A refund for this order at a different amount is a different effect.
    store = _evidence(base, "settlement", COMPLETE, [_refund_record(amount=3000)])
    obs = _fetch_all(store, "settlement")
    d = validate(
        _slot(), Claim(verdict="committed", citations=[o.digest for o in obs]), obs
    )
    check("a hit at the wrong amount is not this slot",
          d.verdict is Verdict.ABSTAIN, f"got {d.verdict}")

    # A lossy source can confirm even though it can never exonerate.
    store = _evidence(base, "webhook", LOSSY, [_refund_record()])
    obs = _fetch_all(store, "webhook")
    d = validate(
        _slot(), Claim(verdict="committed", citations=[o.digest for o in obs]), obs
    )
    check("a lossy source can still confirm",
          d.verdict is Verdict.COMMITTED, f"got {d.verdict}")


# --------------------------------------------------------------------------
# Applying a dossier
# --------------------------------------------------------------------------


def _wire(base: str, *, revoke: str | None = None):
    d = tempfile.mkdtemp(prefix="apply-", dir=base)
    journal = Journal(os.path.join(d, "journal.jsonl"), "test")
    journal.append("anchor", slot="refund", anchor="a" * 32, ts=INTENT_TS - 1)
    journal.append("intent", slot="refund", anchor="a" * 32, amount=AMOUNT,
                   scope="payments:refund", effect="payments.refund", ts=INTENT_TS)
    journal.append("escalated", slot="refund", anchor="a" * 32,
                   reason="opaque tier offers no post-hoc lookup", ts=INTENT_TS + 1)
    perms = PermissionStore(os.path.join(d, "perms.json"))
    perms.grant_all(["payments:refund", "credits:issue"])
    if revoke:
        perms.revoke(revoke)
    return d, journal, perms


class _Receipt:
    def __init__(self, amount: int):
        self.external_id = 99
        self.amount_cents = amount


def test_completion_needs_a_live_permission(base: str) -> None:
    print("\ninvariant 2 holds through the adjudicator")
    store = _evidence(base, "settlement", COMPLETE, [])
    obs = _fetch_all(store, "settlement")

    issued: list[int] = []

    def issue(amount: int):
        issued.append(amount)
        return _Receipt(amount)

    _d, journal, perms = _wire(base, revoke="payments:refund")
    dossier = validate(
        escalated_slots(_d, ORDER)[0],
        Claim(verdict="absent", citations=[o.digest for o in obs]), obs,
    )
    applied = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue
    )
    check("a revoked scope refuses the completion",
          applied.action == second_apply.REFUSED, applied.note)
    check("and no effect is issued", not issued, f"issued={issued}")
    kinds = [r["kind"] for r in journal.read()]
    check("the anchor is not marked adjudicated", "adjudicated" not in kinds,
          f"kinds={kinds}")

    _d, journal, perms = _wire(base)
    dossier = validate(
        escalated_slots(_d, ORDER)[0],
        Claim(verdict="absent", citations=[o.digest for o in obs]), obs,
    )
    applied = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue
    )
    check("a live scope completes it", applied.action == second_apply.COMPLETED,
          applied.note)
    check("and the effect is issued once", issued == [AMOUNT], f"issued={issued}")


def test_completion_anchors_before_it_acts(base: str) -> None:
    print("\nthe adjudicator anchors its own effect before issuing it")
    store = _evidence(base, "settlement", COMPLETE, [])
    obs = _fetch_all(store, "settlement")
    _d, journal, perms = _wire(base)
    dossier = validate(
        escalated_slots(_d, ORDER)[0],
        Claim(verdict="absent", citations=[o.digest for o in obs]), obs,
    )
    order: list[str] = []

    def issue(amount: int):
        # Whatever is durable at this instant is what a crash here would
        # leave behind for the next adjudication to read.
        order.extend(r["kind"] for r in journal.read())
        return _Receipt(amount)

    second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue
    )
    check("adjudication_intent is durable before the call",
          "adjudication_intent" in order, f"durable at call time: {order}")

    # And that timestamp widens the window a source must cover, so a stale
    # report cannot be misread as proof of absence a second time. Fresh
    # directory: this is about the projection, not about the apply above.
    run_dir = tempfile.mkdtemp(prefix="widen-", dir=base)
    j2 = Journal(os.path.join(run_dir, "journal.jsonl"), "test")
    j2.append("intent", slot="refund", anchor="a" * 32, amount=AMOUNT,
              scope="payments:refund", effect="payments.refund")
    j2.append("escalated", slot="refund", anchor="a" * 32, reason="unresolvable")
    before = escalated_slots(run_dir, ORDER)
    j2.append("adjudication_intent", slot="refund", anchor="a" * 32,
              amount=AMOUNT, scope="payments:refund")
    after = escalated_slots(run_dir, ORDER)
    check(
        "a previous attempt widens the coverage requirement",
        len(before) == 1 and len(after) == 1
        and after[0].intent_ts > before[0].intent_ts,
        f"before={[s.intent_ts for s in before]} after={[s.intent_ts for s in after]}",
    )


def test_query_rung_issues_nothing(base: str) -> None:
    print("\nthe query rung creates nothing and needs no permission")
    store = _evidence(base, "settlement", COMPLETE, [_refund_record()])
    obs = _fetch_all(store, "settlement")

    def issue(_amount: int):
        raise AssertionError("the query rung must not issue an effect")

    # Every scope revoked. Reporting what already happened still works,
    # because it creates nothing.
    _d, journal, perms = _wire(base, revoke="payments:refund")
    dossier = validate(
        escalated_slots(_d, ORDER)[0],
        Claim(verdict="committed", citations=[o.digest for o in obs]), obs,
    )
    applied = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue
    )
    check("evidence closes the anchor with no scope held",
          applied.action == second_apply.CLOSED_FROM_EVIDENCE, applied.note)
    rec = [r for r in journal.read() if r["kind"] == "adjudicated"]
    check("and the record carries provenance, not the agent's prose",
          bool(rec) and bool(rec[0]["citations"][0]["provenance"])
          and "reasoning" not in rec[0],
          f"record={rec}")


def test_abstention_is_inert(base: str) -> None:
    print("\nan abstention leaves the halt exactly where it was")
    store = _evidence(base, "webhook", LOSSY, [])
    obs = _fetch_all(store, "webhook")
    dossier = validate(
        _slot(), Claim(verdict="absent", citations=[o.digest for o in obs]), obs
    )
    _d, journal, perms = _wire(base)

    def issue(_amount: int):
        raise AssertionError("an abstention must not issue an effect")

    applied = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue
    )
    check("nothing is applied", applied.action == second_apply.NONE, applied.note)
    kinds = [r["kind"] for r in journal.read()]
    check("an audit record is written", "adjudication_abstained" in kinds, f"{kinds}")
    check("but the anchor is not adjudicated", "adjudicated" not in kinds, f"{kinds}")


def _absence_dossier(base: str, run_dir: str):
    store = _evidence(base, "settlement", COMPLETE, [])
    obs = _fetch_all(store, "settlement")
    return validate(
        escalated_slots(run_dir, ORDER)[0],
        Claim(verdict="absent", citations=[o.digest for o in obs]), obs,
    )


def test_dossier_must_match_live_intent(base: str) -> None:
    print("\na resolving dossier must be bound to the live halted intent")
    run_dir, journal, perms = _wire(base)
    dossier = _absence_dossier(base, run_dir)

    def issue(_amount: int):
        raise AssertionError("a mismatched dossier must not issue an effect")

    bad = {
        "unbound dossier": replace(dossier, journal_revision=None),
        "wrong anchor": replace(dossier, anchor="b" * 32),
        "wrong slot": replace(dossier, slot="credit"),
        "wrong dossier amount": replace(dossier, amount_cents=AMOUNT + 1),
        "wrong proposal amount": replace(
            dossier, proposal=replace(dossier.proposal, amount_cents=AMOUNT + 1),
        ),
        "wrong proposal scope": replace(
            dossier, proposal=replace(dossier.proposal, scope="credits:issue"),
        ),
    }
    before = journal.read()
    for name, candidate in bad.items():
        result = second_apply.apply_dossier(
            candidate, journal=journal, perms=perms, issue_effect=issue,
        )
        check(f"refuses {name}", result.action == second_apply.INCONSISTENT, result.note)
    check("mismatches leave durable state unchanged", journal.read() == before)

    empty = Journal(os.path.join(base, "empty-journal.jsonl"), "empty")
    result = second_apply.apply_dossier(
        dossier, journal=empty, perms=perms, issue_effect=issue,
    )
    check("refuses a journal with no halted slot",
          result.action == second_apply.INCONSISTENT, result.note)

    journal.append("escalated", slot="refund", anchor="b" * 32, reason="mismatched")
    check("an escalation with a different anchor is not adjudicable",
          not escalated_slots(run_dir, ORDER))


def test_repeat_and_stale_dossiers_are_inert(base: str) -> None:
    print("\nrepeated and stale dossiers cannot create another effect")
    run_dir, journal, perms = _wire(base)
    dossier = _absence_dossier(base, run_dir)
    issued: list[int] = []

    def issue(amount: int):
        issued.append(amount)
        return _Receipt(amount)

    # Neither a failed permission check nor unrelated workflow/audit events
    # change what could have happened to the refund slot.
    perms.revoke("payments:refund")
    denied = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue,
    )
    check("permission denial still leaves a current dossier",
          denied.action == second_apply.REFUSED
          and escalated_slots(run_dir, ORDER)[0].journal_revision == dossier.journal_revision)
    perms.grant_all(["payments:refund"])
    journal.append("adjudication_abstained", slot="refund", anchor=dossier.anchor)
    journal.append("attempt_start", runtime="anchored", replaying=True)
    journal.append("intent", slot="credit", anchor="c" * 32, amount=100,
                   scope="credits:issue")
    first = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue,
    )
    check("audit and unrelated records preserve a fresh completion",
          first.action == second_apply.COMPLETED, first.note)
    before = journal.read()
    again = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue,
    )
    check("repeating a completed dossier is refused",
          again.action == second_apply.INCONSISTENT, again.note)
    check("repeat created no effect or resolution record",
          issued == [AMOUNT] and journal.read() == before, f"issued={issued}")

    for kind in ("intent", "adjudication_intent", "settled", "resolved", "adjudicated"):
        run_dir, journal, perms = _wire(base)
        dossier = _absence_dossier(base, run_dir)
        journal.append(kind, slot="refund", anchor=dossier.anchor, amount=AMOUNT,
                       scope="payments:refund", ts=INTENT_TS)
        before = journal.read()
        count = len(issued)
        result = second_apply.apply_dossier(
            dossier, journal=journal, perms=perms, issue_effect=issue,
        )
        check(f"a newer {kind} invalidates an old dossier even at the same timestamp",
              result.action == second_apply.INCONSISTENT
              and len(issued) == count and journal.read() == before, result.note)


def test_query_dossier_cannot_overwrite_new_state(base: str) -> None:
    print("\na stale query cannot rewrite a slot's resolution")
    run_dir, journal, perms = _wire(base)
    store = _evidence(base, "settlement", COMPLETE, [_refund_record()])
    obs = _fetch_all(store, "settlement")
    dossier = validate(
        escalated_slots(run_dir, ORDER)[0],
        Claim(verdict="committed", citations=[o.digest for o in obs]), obs,
    )
    first = second_apply.apply_dossier(dossier, journal=journal, perms=perms)
    before = journal.read()
    again = second_apply.apply_dossier(dossier, journal=journal, perms=perms)
    check("query closes once and its repeat leaves the resolution unchanged",
          first.action == second_apply.CLOSED_FROM_EVIDENCE
          and again.action == second_apply.INCONSISTENT and journal.read() == before)

    run_dir, journal, perms = _wire(base)
    dossier = validate(
        escalated_slots(run_dir, ORDER)[0],
        Claim(verdict="committed", citations=[o.digest for o in obs]), obs,
    )
    journal.append("adjudication_intent", slot="refund", anchor=dossier.anchor,
                   amount=AMOUNT, scope="payments:refund", ts=INTENT_TS)
    result = second_apply.apply_dossier(dossier, journal=journal, perms=perms)
    check("a query prepared before a new attempt is refused",
          result.action == second_apply.INCONSISTENT, result.note)


def test_failed_completion_needs_fresh_evidence(base: str) -> None:
    print("\nan ambiguous completion cannot reuse its old absence evidence")
    for landed in (False, True):
        run_dir, journal, perms = _wire(base)
        dossier = _absence_dossier(base, run_dir)
        issued: list[int] = []

        def fails(amount: int, *, effect_landed=landed, effects=issued):
            if effect_landed:
                effects.append(amount)
            raise ConnectionError("lost acknowledgement")

        try:
            second_apply.apply_dossier(
                dossier, journal=journal, perms=perms, issue_effect=fails,
            )
        except ConnectionError:
            pass
        else:
            check("the injected effect failure occurred", False)

        # Reopen the journal, as a new process would after a crash. It knows
        # an attempt was possible, but the effect's outcome is still unknown.
        journal = Journal(journal.path, "restarted")

        def succeeds(amount: int, *, effects=issued):
            effects.append(amount)
            return _Receipt(amount)

        before = journal.read()
        replay = second_apply.apply_dossier(
            dossier, journal=journal, perms=perms, issue_effect=succeeds,
        )
        check(f"failed attempt (landed={landed}) refuses its old dossier on restart",
              replay.action == second_apply.INCONSISTENT and journal.read() == before,
              replay.note)
        fresh_slot = escalated_slots(run_dir, ORDER)[0]
        old_evidence = _absence_dossier(base, run_dir)
        check(f"failed attempt (landed={landed}) makes the old report insufficient",
              old_evidence.verdict is Verdict.ABSTAIN
              and fresh_slot.intent_ts > INTENT_TS)

        records = [_refund_record(ts=fresh_slot.intent_ts + 0.5)] if landed else []
        coverage = {"kind": "complete_until", "cutoff_ts": fresh_slot.intent_ts + 100}
        store = _evidence(base, "settlement", coverage, records)
        obs = _fetch_all(store, "settlement")
        fresh = validate(
            fresh_slot,
            Claim(verdict="committed" if landed else "absent",
                  citations=[o.digest for o in obs]), obs,
        )
        result = second_apply.apply_dossier(
            fresh, journal=journal, perms=perms, issue_effect=succeeds,
        )
        expected = second_apply.CLOSED_FROM_EVIDENCE if landed else second_apply.COMPLETED
        check(f"fresh evidence (landed={landed}) safely resolves the new uncertainty",
              result.action == expected and issued == [AMOUNT],
              f"{result.note}; issued={issued}")


def test_trusting_control_keeps_the_same_state_guard(base: str) -> None:
    print("\nthe trusting control has state safety but still lacks evidence validation")
    run_dir, journal, perms = _wire(base)
    store = _evidence(base, "webhook", LOSSY, [])

    class UnsupportedAbsence:
        def propose_pointers(self, _view):
            return []

        def conclude(self, _view, _observations):
            return Claim(verdict="absent", reasoning=["unsupported guess"])

    dossier = adjudicate_trusting(
        escalated_slots(run_dir, ORDER)[0], store, UnsupportedAbsence(),
    )
    issued: list[int] = []

    def issue(amount: int):
        issued.append(amount)
        return _Receipt(amount)

    first = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue,
    )
    again = second_apply.apply_dossier(
        dossier, journal=journal, perms=perms, issue_effect=issue,
    )
    check("the trusting baseline still acts on unsupported absence",
          first.action == second_apply.COMPLETED and not dossier.citations, first.note)
    check("but the same state guard prevents repeating its dossier",
          again.action == second_apply.INCONSISTENT and issued == [AMOUNT], again.note)


# --------------------------------------------------------------------------
# End to end, under a real SIGKILL
# --------------------------------------------------------------------------


def test_end_to_end(base: str) -> None:
    print("\nend to end: a halted anchor closes and the workflow finishes")
    from experiments.harness import run_trial
    from experiments.run_adjudication import one_case

    source = None
    for _ in range(20):
        t = run_trial(base, "anchored", "opaque", "in_flight", keep=True)
        if t.verdict == "escalated" and t.run_dir:
            source = t.run_dir
            break
        shutil.rmtree(t.run_dir or "", ignore_errors=True)
    if source is None:
        check("produced an escalated anchor", False, "none in 20 trials")
        return
    check("an opaque in-flight crash escalates", True)

    run_id = os.path.basename(source).split("__")[-1]
    work = os.path.join(base, "e2e")
    os.makedirs(work, exist_ok=True)
    rng = random.Random(0)

    case = one_case(source, f"order-{run_id}", run_id, "none", "competent",
                    "validated", work, rng)
    check("with no evidence available it stays halted",
          case["grade"] == "abstained", f"{case['grade']}: {case['why']}")

    case = one_case(source, f"order-{run_id}", run_id, "settlement", "competent",
                    "validated", work, rng)
    check("with a covering report the anchor closes",
          case["grade"] == "resolved", f"{case['grade']}: {case['why']}")
    check("no second refund is issued",
          len(case["ledger_after"]) == 1, f"ledger={case['ledger_after']}")
    check("and the workflow resumes to a committed report",
          case["workflow_after_resume"] == "committed",
          f"resumed={case['workflow_after_resume']}")

    case = one_case(source, f"order-{run_id}", run_id, "stale_settlement",
                    "adversarial", "validated", work, rng)
    check("an adversarial agent on a stale report cannot close it",
          case["grade"] in ("abstained", "refused"),
          f"{case['grade']}: {case['why']}")


def main() -> int:
    base = tempfile.mkdtemp(prefix="belay-second-")
    try:
        test_import_direction()
        test_pointers_must_resolve(base)
        test_citations_must_be_real(base)
        test_absence_needs_coverage_not_silence(base)
        test_commitment_needs_a_matching_record(base)
        test_completion_needs_a_live_permission(base)
        test_completion_anchors_before_it_acts(base)
        test_query_rung_issues_nothing(base)
        test_abstention_is_inert(base)
        test_dossier_must_match_live_intent(base)
        test_repeat_and_stale_dossiers_are_inert(base)
        test_query_dossier_cannot_overwrite_new_state(base)
        test_failed_completion_needs_fresh_evidence(base)
        test_trusting_control_keeps_the_same_state_guard(base)
        test_end_to_end(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print(f"\n{_passed} passed, {len(_failed)} failed")
    for f in _failed:
        print(f"  {f}")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
