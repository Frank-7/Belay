"""Record a recovery desk demo using real process deaths and sandbox payments.

    python3 experiments/recovery_demo.py
    python3 experiments/recovery_demo.py --agent openai --model MODEL

The JSON is a recording, not a runtime API. The recovery agent sees evidence
artifacts only; the experiment reads the payment ledger to grade its work.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.authz import PermissionStore  # noqa: E402
from belay.journal import Journal  # noqa: E402
from experiments import build_evidence  # noqa: E402
from experiments.harness import run_trial  # noqa: E402
from experiments.run_adjudication import _grade, _refunds, _resume  # noqa: E402
from second.adjudicate import adjudicate, escalated_slots  # noqa: E402
from second.agent import DebugAgent  # noqa: E402
from second.apply import apply_dossier  # noqa: E402
from second.dossier import Claim  # noqa: E402
from second.evidence import EvidenceStore  # noqa: E402
from services.ledger import Ledger  # noqa: E402
from services.payments import build as build_payments  # noqa: E402


def _heuristic():
    return DebugAgent(hallucination_p=0, overconfidence_p=0, laziness_p=0, seed=0)


class _UnsafeClaim(DebugAgent):
    """A labelled fault injection: confidently infer absence from stale silence."""

    def __init__(self):
        super().__init__(hallucination_p=0, overconfidence_p=0, laziness_p=0, seed=0)

    def conclude(self, view, observations):
        return Claim(
            verdict="absent",
            citations=[o.digest for o in observations],
            reasoning=["The report contains no refund. I propose completing it."],
        )


class _RecordingAgent:
    def __init__(self, delegate):
        self.delegate = delegate
        self.pointers = []
        self.observations = []
        self.claim = None

    def propose_pointers(self, view):
        self.pointers = list(self.delegate.propose_pointers(view) or [])
        return self.pointers

    def conclude(self, view, observations):
        self.observations = [o.as_dict() for o in observations]
        claim = self.delegate.conclude(view, observations)
        self.claim = claim.as_dict()
        return claim


def _step(run_dir, run_id, order_id, tier, agent, label, title, *, revoke=False):
    slots = escalated_slots(run_dir, order_id)
    if len(slots) != 1:
        raise RuntimeError("demo requires exactly one unresolved refund slot")
    slot = slots[0]
    evidence_dir = build_evidence.build(
        run_dir, order_id, tier, intent_ts=slot.intent_ts,
        evidence_dirname=f"evidence-{tier}", rng=random.Random(0),
    )
    recorder = _RecordingAgent(agent)
    started = time.perf_counter()
    dossier = adjudicate(slot, EvidenceStore(evidence_dir), recorder)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    before = _refunds(run_dir, order_id)
    journal = Journal(os.path.join(run_dir, "journal.jsonl"), run_id)
    journal_before = len(journal.read())
    perms = PermissionStore(os.path.join(run_dir, "perms.json"))
    if revoke:
        # Deliberately revoke AFTER the proposal to exercise the live check.
        perms.revoke("payments:refund")
    ledger = Ledger(os.path.join(run_dir, "ledger.db"))
    try:
        payments = build_payments("opaque", ledger)
        applied = apply_dossier(
            dossier, journal=journal, perms=perms,
            issue_effect=lambda amount: payments.refund(order_id, amount),
            operator="recorded-recovery-demo",
        )
    finally:
        ledger.close()
    after = _refunds(run_dir, order_id)
    grade, why = _grade(applied.action, dossier, before, after)
    resumed = _resume(run_dir, run_id, order_id) if grade == "resolved" else None
    final = _refunds(run_dir, order_id)
    if final != after:
        grade, why = "false", "resume changed the payment ledger after adjudication"
    metrics = agent.metrics() if callable(getattr(agent, "metrics", None)) else None
    return {
        "title": title, "agent": label, "evidence_tier": tier,
        "intent_ts": slot.intent_ts, "pointers": recorder.pointers,
        "observations": recorder.observations, "claim": recorder.claim,
        "dossier": dossier.as_dict(), "applied": applied.as_dict(),
        "ledger_before": before, "ledger_after": final,
        "grade": grade, "why": why, "workflow_after_resume": resumed,
        "permission_revoked_after_proposal": revoke,
        "journal": journal.read()[journal_before:],
        "elapsed_ms": elapsed_ms, "model_metrics": metrics,
    }


def generate_demo(agent_factory=None, *, agent_label="Simulated heuristic") -> dict:
    """Return an inspectable recording. Default needs no credentials or network.

    An injected factory returns an agent with propose_pointers/conclude.
    Outcomes are recorded even when a live model abstains or its request fails.
    """
    factory = agent_factory or _heuristic
    with tempfile.TemporaryDirectory(prefix="belay-recovery-demo-") as base:
        sources = {}
        for crash_at in ("in_flight", "after_intent"):
            trial = run_trial(
                base, "anchored", "opaque", crash_at, keep=True,
                journal_decision=True, force_plans=("full_refund", "full_refund"),
            )
            if not trial.crashed_as_asked or trial.verdict != "escalated":
                raise RuntimeError(
                    f"{crash_at}: expected confirmed SIGKILL and escalation; "
                    "run this demo on Linux/macOS (Windows: use WSL)"
                )
            sources[crash_at] = trial

        cases = []
        for case_id, title, crash_at, revoke in (
            ("lost_ack", "The refund landed. The acknowledgment did not.", "in_flight", False),
            ("complete_absent", "The refund never reached the processor.", "after_intent", False),
            ("revoked", "Permission changes while recovery is being reviewed.", "after_intent", True),
        ):
            trial = sources[crash_at]
            run_dir = os.path.join(base, case_id)
            shutil.copytree(trial.run_dir, run_dir)
            run_id = os.path.basename(trial.run_dir).split("__")[-1]
            order_id = f"order-{run_id}"
            slot = escalated_slots(run_dir, order_id)[0]
            initial = _refunds(run_dir, order_id)
            stages = []
            if case_id == "lost_ack":
                stages.append(_step(
                    run_dir, run_id, order_id, "none", factory(), agent_label,
                    "No evidence: keep the refund paused",
                ))
                stages.append(_step(
                    run_dir, run_id, order_id, "stale_settlement", _UnsafeClaim(),
                    "Injected unsafe claim (simulated)",
                    "Stale report: challenge the verifier",
                ))
            stages.append(_step(
                run_dir, run_id, order_id, "settlement", factory(), agent_label,
                "Fresh settlement report: verify the evidence", revoke=revoke,
            ))
            cases.append({
                "id": case_id, "title": title, "order_id": order_id,
                "amount_cents": 5000, "anchor": slot.anchor, "crash_at": crash_at,
                "crash_confirmed": trial.crashed_as_asked,
                "initial_status": trial.verdict, "ledger_initial": initial,
                "stages": stages,
            })
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "execution": "recorded", "payments": "sandbox SQLite ledger",
        "agent": agent_label,
        "assumptions": [
            "One refund slot per order; records match by order and amount.",
            "Evidence sources and their coverage declarations are trusted inputs.",
            "Sandbox process crashes are real SIGKILLs; no real payments are made.",
        ],
        "cases": cases,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", choices=("heuristic", "openai"), default="heuristic")
    parser.add_argument("--model", help="live model name (or OPENAI_MODEL)")
    parser.add_argument("--out", default=os.path.join(ROOT, "tmp-runs", "recovery-demo.json"))
    args = parser.parse_args(argv)
    factory = None
    label = "Simulated heuristic"
    if args.agent == "openai":
        from second.live_agent import OpenAIRecoveryAgent

        # Validate configuration before performing any crash experiments.
        try:
            configured = OpenAIRecoveryAgent.from_env(model=args.model)
        except ValueError as exc:
            parser.error(str(exc))
        factory = lambda: OpenAIRecoveryAgent.from_env(model=args.model)  # noqa: E731
        label = f"Live OpenAI model: {configured.model}"
    elif args.model:
        parser.error("--model requires --agent openai")
    demo = generate_demo(factory, agent_label=label)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(demo, fh, indent=2)
        fh.write("\n")
    for case in demo["cases"]:
        for stage in case["stages"]:
            print(f"{case['id']}: {stage['grade']} / {stage['applied']['action']}")
    print(f"Recorded demo: {args.out}")
    stages = [stage for case in demo["cases"] for stage in case["stages"]]
    if any(stage["grade"] == "false" for stage in stages):
        print("A recovery violated the contract; inspect the recording.", file=sys.stderr)
        return 1
    if any((stage.get("model_metrics") or {}).get("errors") for stage in stages):
        print("Model requests failed; the recording includes the resulting abstentions.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
