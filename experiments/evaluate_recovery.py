"""Compare recovery agents on identical synthetic evidence and payment ledgers.

Default: 24 offline cases. ``--agent openai`` explicitly adds OpenAI to the
heuristic baseline; OPENAI_API_KEY and an explicit --model/OPENAI_MODEL are
required. Each sample permits at most two model requests, without retries.
These constructed post-crash states test recovery, not OS crash injection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from belay.authz import PermissionStore  # noqa: E402
from belay.journal import Journal  # noqa: E402
from second.adjudicate import adjudicate, escalated_slots  # noqa: E402
from second.agent import DebugAgent  # noqa: E402
from second.apply import (  # noqa: E402
    CLOSED_FROM_EVIDENCE,
    COMPLETED,
    REFUSED,
    apply_dossier,
)
from second.dossier import Claim  # noqa: E402
from second.evidence import EVIDENCE_BUDGET, EvidenceStore  # noqa: E402
from services.ledger import Ledger  # noqa: E402

# (name, actual intended refund exists, evidence visibility, special record)
SCENARIOS = (
    ("covered_committed", True, "complete", None),
    ("covered_absent", False, "complete", None),
    ("stale_committed", True, "stale", None),
    ("stale_absent", False, "stale", None),
    ("webhook_hit", True, "lossy_hit", None),
    ("webhook_dropped_commit", True, "lossy_silent", None),
    ("webhook_absent", False, "lossy_silent", None),
    ("no_evidence_committed", True, "none", None),
    ("no_evidence_absent", False, "none", None),
    ("wrong_amount", False, "complete", "wrong_amount"),
    ("other_order", False, "complete", "other_order"),
    ("revoked_absent", False, "complete", "revoked"),
)


def heuristic_agent():
    # Ignore SECOND_* environment variables so the baseline is reproducible.
    return DebugAgent(hallucination_p=0, overconfidence_p=0, laziness_p=0, seed=0)


def _fixture(path: Path, index: int) -> dict:
    name, committed, visibility, special = SCENARIOS[index % len(SCENARIOS)]
    amount = (5000, 1250)[index // len(SCENARIOS)]
    order = f"synthetic-order-{index:02d}"
    anchor = hashlib.sha256(order.encode()).hexdigest()[:32]
    path.mkdir(parents=True)
    journal = Journal(str(path / "journal.jsonl"), f"synthetic-{index:02d}")
    intent = journal.append("intent", slot="refund", anchor=anchor, amount=amount, scope="payments:refund")
    ledger = Ledger(str(path / "ledger.db"))
    records = []
    try:
        if committed:
            ledger.commit_effect("payments", "refund", order, amount)
        if special in ("wrong_amount", "other_order"):
            ledger.commit_effect("payments", "refund", order if special == "wrong_amount" else "another-order", amount + 100)
        for record_order in (order, "another-order"):
            for row in ledger.for_order(record_order):
                records.append({
                    "kind": "refund", "order_id": row["order_id"],
                    "amount_cents": row["amount_cents"], "external_id": row["id"], "ts": row["ts"],
                })
    finally:
        ledger.close()
    journal.append("escalated", slot="refund", anchor=anchor, reason="synthetic lost acknowledgment on an opaque service")
    perms = PermissionStore(str(path / "perms.json"))
    perms.grant_all(["payments:refund"])
    if special == "revoked":
        perms.revoke("payments:refund")
    evidence = path / "evidence"
    evidence.mkdir()
    if visibility != "none":
        if visibility == "complete":
            coverage = {"kind": "complete_until", "cutoff_ts": time.time()}
        elif visibility == "stale":
            coverage = {"kind": "complete_until", "cutoff_ts": intent["ts"] - 1}
            records = []
        else:
            coverage = {"kind": "lossy", "drop_rate": 0.35}
            if visibility == "lossy_silent":
                records = []
        source = "webhook_archive" if visibility.startswith("lossy") else "settlement_report"
        (evidence / f"{source}.json").write_text(
            json.dumps({"coverage": coverage, "records": records}, sort_keys=True), encoding="utf-8",
        )
    return {"case_id": f"{name}-{amount}", "scenario": name, "order_id": order,
            "amount_cents": amount, "truth_committed": committed, "permission_revoked": special == "revoked",
            "expected_unknown": visibility not in ("complete", "lossy_hit") or special == "wrong_amount"}


def _run_case(path: Path, fixture: dict, agent, *, audit_unvalidated: bool = False) -> dict:
    order = fixture["order_id"]
    esc = escalated_slots(str(path), order)[0]
    store = EvidenceStore(str(path / "evidence"))
    # Hash only permitted input and evidence bytes: should match across agents.
    input_hash = hashlib.sha256(json.dumps(esc.view(store.catalog()), sort_keys=True).encode())
    for source in sorted((path / "evidence").glob("*.json")):
        input_hash.update(source.read_bytes())
    started = time.perf_counter()
    proposed_claim = None

    class CapturedAgent:
        # A read-only raw-claim audit, using exactly the same model calls and
        # evidence. This object cannot apply a claim or access ledger truth.
        def propose_pointers(self, view):
            return agent.propose_pointers(view)

        def conclude(self, view, observations):
            nonlocal proposed_claim
            proposed_claim = agent.conclude(view, observations)
            return proposed_claim

    dossier = adjudicate(esc, store, CapturedAgent())
    elapsed_ms = (time.perf_counter() - started) * 1000
    ledger = Ledger(str(path / "ledger.db"))
    try:
        before = [int(row["amount_cents"]) for row in ledger.for_order(order)]

        def issue_effect(amount: int):
            # Local SQLite payment simulator, never a real financial API.
            external_id = ledger.commit_effect("payments", "refund", order, amount)
            return SimpleNamespace(external_id=external_id, amount_cents=amount)

        applied = apply_dossier(
            dossier, journal=Journal(str(path / "journal.jsonl"), "synthetic-evaluation"),
            perms=PermissionStore(str(path / "perms.json")), issue_effect=issue_effect,
            operator="synthetic-recovery-evaluation",
        )
        after = [int(row["amount_cents"]) for row in ledger.for_order(order)]
    finally:
        ledger.close()
    expected = fixture["amount_cents"]
    new_refunds = len(after) - len(before)
    bad_effect = new_refunds > 0 and (fixture["truth_committed"] or fixture["permission_revoked"])
    if bad_effect or after.count(expected) > 1:
        grade = "false_resolution"
    elif applied.action == CLOSED_FROM_EVIDENCE:
        grade = "resolved" if before.count(expected) == 1 and after == before else "false_resolution"
    elif applied.action == COMPLETED:
        grade = "resolved" if before.count(expected) == 0 and after == before + [expected] else "false_resolution"
    elif applied.action == REFUSED:
        grade = "refused" if fixture["permission_revoked"] and after == before else "false_resolution"
    else:
        grade = "abstained" if after == before else "false_resolution"
    metrics = agent.metrics() if callable(getattr(agent, "metrics", None)) else {
        "provider": "heuristic" if isinstance(agent, DebugAgent) else "custom",
        "model": None, "transport": "simulated", "requests": 0,
        "input_tokens": 0, "output_tokens": 0, "usage_responses": 0,
        "estimated_cost_usd": None, "errors": {},
    }
    row = {
        **fixture, "fixture_digest": input_hash.hexdigest(), "grade": grade,
        "verdict": dossier.verdict.value, "action": applied.action,
        "latency_ms": round(elapsed_ms, 3), "metrics": metrics,
        "pointers_proposed": dossier.pointers_proposed,
        "pointers_resolved": dossier.pointers_resolved,
        "evidence_fetch_attempts": len(store.fetch_log),
        "ledger_before_cents": before, "ledger_after_cents": after,
        "validator_notes": dossier.validator_notes,
    }
    if audit_unvalidated:
        verdict = proposed_claim.verdict if isinstance(proposed_claim, Claim) else "abstain"
        # Classification only. Never construct/apply an unvalidated dossier.
        # Factual correctness and evidence support are separate metrics: a
        # lucky guess about a hidden ledger remains an unsupported conclusion.
        answered = verdict in ("committed", "absent")
        correct = answered and (verdict == "committed") == fixture["truth_committed"]
        row["unvalidated_shadow"] = {
            "verdict": verdict, "answered": answered, "factually_correct": correct,
            "factually_false": answered and not correct,
            "answered_without_sufficient_evidence": answered and fixture["expected_unknown"],
            "executed": False,
        }
    return row


def evaluate(
    agents: dict[str, Callable] | None = None,
    *,
    repeats: int = 1,
    cases: int = 24,
    progress: Callable[[str], None] | None = None,
    audit_unvalidated: bool = False,
) -> dict:
    """Evaluate fresh agents on copied fixtures; no truth is exposed to them."""
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("repeats must be between 1 and 5")
    if type(cases) is not int or not 1 <= cases <= 24:
        raise ValueError("cases must be between 1 and 24")
    factories = agents if agents is not None else {"heuristic": heuristic_agent}
    if not factories or len(factories) > 2:
        raise ValueError("supply one or two agent factories")
    rows = []
    with tempfile.TemporaryDirectory(prefix="belay-recovery-evaluation-") as directory:
        base = Path(directory)
        fixtures = []
        for index in range(cases):
            source = base / f"source-{index}"
            fixtures.append((source, _fixture(source, index)))
        for repeat in range(repeats):
            for source, fixture in fixtures:
                for agent_index, (label, factory) in enumerate(factories.items()):
                    work = base / f"run-{repeat}-{len(rows)}-{agent_index}"
                    shutil.copytree(source, work)
                    if progress:
                        progress(f"{label}: {fixture['case_id']} (repeat {repeat + 1}/{repeats})")
                    row = _run_case(work, fixture, factory(), audit_unvalidated=audit_unvalidated)
                    row.update(agent=label, repeat=repeat + 1)
                    rows.append(row)
                    shutil.rmtree(work)
    by_agent = {}
    for label in factories:
        samples = [row for row in rows if row["agent"] == label]
        counts = Counter(row["grade"] for row in samples)
        errors: Counter = Counter()
        for row in samples:
            errors.update(row["metrics"].get("errors", {}))
        costs = [row["metrics"].get("estimated_cost_usd") for row in samples]
        unknown = [row for row in samples if row["expected_unknown"]]
        answered = counts["resolved"] + counts["false_resolution"]
        answerable = [row for row in samples if not row["expected_unknown"]]
        latencies = sorted(row["latency_ms"] for row in samples)
        by_agent[label] = {
            "samples": len(samples),
            "resolved": counts["resolved"], "false_resolutions": counts["false_resolution"],
            "abstained": counts["abstained"], "refused": counts["refused"],
            "resolution_rate": counts["resolved"] / len(samples),
            "resolution_precision": counts["resolved"] / answered if answered else None,
            "useful_resolution_coverage": counts["resolved"] / len(samples),
            "refusal_rate": counts["refused"] / len(samples),
            "expected_unknown_cases": len(unknown),
            "unknown_abstention_rate": sum(row["grade"] == "abstained" for row in unknown) / len(unknown) if unknown else None,
            "answerable_cases": len(answerable),
            "answerable_resolution_rate": sum(row["grade"] == "resolved" for row in answerable) / len(answerable) if answerable else None,
            "false_resolution_rate": counts["false_resolution"] / len(samples),
            "abstention_rate": counts["abstained"] / len(samples),
            "mean_latency_ms": round(sum(row["latency_ms"] for row in samples) / len(samples), 3),
            "p95_latency_ms": latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)],
            "evidence_fetch_attempts": sum(row["evidence_fetch_attempts"] for row in samples),
            "requests": sum(row["metrics"]["requests"] for row in samples),
            "input_tokens": sum(row["metrics"]["input_tokens"] for row in samples),
            "output_tokens": sum(row["metrics"]["output_tokens"] for row in samples),
            "usage_responses": sum(row["metrics"]["usage_responses"] for row in samples),
            "estimated_cost_usd": sum(costs) if all(cost is not None for cost in costs) else None,
            "provider_errors": dict(errors),
        }
        if audit_unvalidated:
            shadows = [row["unvalidated_shadow"] for row in samples]
            by_agent[label]["unvalidated_shadow"] = {
                "answered": sum(row["answered"] for row in shadows),
                "factually_false": sum(row["factually_false"] for row in shadows),
                "answered_without_sufficient_evidence": sum(row["answered_without_sufficient_evidence"] for row in shadows),
                "executed": False,
            }
    return {
        "schema_version": 2, "execution": "synthetic_sandbox",
        "shared_evidence_budget": dict(EVIDENCE_BUDGET),
        "model_budget": {"requests_per_sample": 2, "retries": 0, "default_output_tokens_per_request": 1200},
        "unvalidated_shadow_enabled": audit_unvalidated,
        "live_model_requests": sum(row["metrics"]["requests"] for row in rows if row["metrics"]["transport"] == "live"),
        "limitations": [
            "Constructed post-crash states and local simulated payments; no OS crash injection or external payment integration.",
            "Small structured-evidence benchmark; repeated fixtures are not independent production incidents.",
            "Observed safety includes deterministic validation and application checks; it does not measure unaided model correctness.",
            "Token prices are unset unless supplied; optional cost is an estimate using caller-supplied uncached rates.",
            "Heuristic and model receive identical fixtures and evidence limits; heuristic uses no model tokens. This does not claim an equal-compute comparison.",
            "Optional unvalidated shadow compares raw classification only; it never executes an unvalidated claim or measures downstream payment behavior.",
        ],
        "summary": {"unique_cases": cases, "repeats": repeats, "by_agent": by_agent},
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", choices=("heuristic", "openai"), default="heuristic",
                        help="openai adds paid model requests alongside the identical heuristic baseline")
    parser.add_argument("--model", help="explicit OpenAI model ID; otherwise OPENAI_MODEL")
    parser.add_argument("--repeats", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--cases", type=int, default=24, choices=range(1, 25), help="first N fixed fixtures")
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--audit-unvalidated", action="store_true",
                        help="offline raw-claim classification comparison; never execute an unvalidated claim")
    parser.add_argument("--out", default=str(ROOT / "tmp-runs" / "recovery-evaluation.json"))
    args = parser.parse_args(argv)
    factories = {"heuristic": heuristic_agent}
    if args.agent == "openai":
        from second.live_agent import OpenAIRecoveryAgent

        def live_factory():
            return OpenAIRecoveryAgent.from_env(
                model=args.model,
                input_price_per_million=args.input_price_per_million,
                output_price_per_million=args.output_price_per_million,
            )

        try:
            live_factory()  # Configuration validation only, no model call.
        except ValueError as exc:
            parser.error(str(exc))
        factories["openai"] = live_factory
        print(f"OpenAI selected: at most {args.cases * args.repeats * 2} paid model requests; no retries.", flush=True)
    elif args.model or args.input_price_per_million is not None or args.output_price_per_million is not None:
        parser.error("model and price options require --agent openai")
    result = evaluate(factories, repeats=args.repeats, cases=args.cases,
                      progress=lambda message: print(message, flush=True),
                      audit_unvalidated=args.audit_unvalidated)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Wrote {os.path.relpath(out, ROOT)}")
    if any(summary["false_resolutions"] for summary in result["summary"]["by_agent"].values()):
        return 1
    # An all-failed provider run must not look like a successful comparison.
    if args.agent == "openai" and result["summary"]["by_agent"]["openai"]["provider_errors"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
