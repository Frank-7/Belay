"""Run frozen, constructed recovery boundary cases without issuing effects.

Authored separately from evaluate_recovery's fixtures. Once authored these
cases are public regression inputs, not a continually fresh statistical holdout.
Defaults to the deterministic heuristic; no credentials or network are needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.evaluate_recovery import heuristic_agent  # noqa: E402
from second.adjudicate import EscalatedSlot, adjudicate  # noqa: E402
from second.evidence import EVIDENCE_BUDGET, EvidenceStore  # noqa: E402

FIXTURES = Path(__file__).with_name("fixtures") / "recovery_holdout_v1.json"


def run_holdout(agent_factory=heuristic_agent, *, repeats: int = 1) -> dict:
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("repeats must be between 1 and 5")
    raw = FIXTURES.read_bytes()
    manifest = json.loads(raw)
    rows = []
    with tempfile.TemporaryDirectory(prefix="belay-recovery-holdout-") as directory:
        for repeat in range(repeats):
            for fixture in manifest["cases"]:
                evidence = Path(directory) / f"{repeat}-{fixture['case_id']}"
                evidence.mkdir()
                for name, document in fixture["sources"].items():
                    (evidence / f"{name}.json").write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
                esc = EscalatedSlot(
                    anchor=hashlib.sha256(f"{manifest['authoring_seed']}:{fixture['case_id']}".encode()).hexdigest()[:32],
                    slot="refund", order_id=manifest["order_id"], amount_cents=manifest["amount_cents"],
                    scope="payments:refund", intent_ts=manifest["intent_ts"], reason="constructed holdout",
                )
                store = EvidenceStore(str(evidence))
                agent = agent_factory()
                started = time.perf_counter()
                dossier = adjudicate(esc, store, agent)
                rows.append({
                    "case_id": fixture["case_id"], "repeat": repeat + 1,
                    "fixture_digest": hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest(),
                    "expected_verdict": fixture["expected_verdict"], "verdict": dossier.verdict.value,
                    "correct": dossier.verdict.value == fixture["expected_verdict"],
                    "false_resolution": dossier.resolved and dossier.verdict.value != fixture["expected_verdict"],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "evidence_fetch_attempts": len(store.fetch_log),
                    "validator_notes": dossier.validator_notes,
                    "metrics": agent.metrics() if callable(getattr(agent, "metrics", None)) else {"requests": 0, "transport": "offline"},
                })
    counts = Counter(row["verdict"] for row in rows)
    return {
        "schema_version": 1, "suite": manifest["version"],
        "status": manifest["status"], "authoring_seed": manifest["authoring_seed"],
        "fixture_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "fixture_hash_format": "UTF-8 JSON with sorted keys and compact separators; independent of checkout line endings",
        "shared_evidence_budget": dict(EVIDENCE_BUDGET),
        "execution": "classification_only_no_effect_issuer",
        "summary": {
            "unique_cases": len(manifest["cases"]), "repeats": repeats, "samples": len(rows),
            "correct": sum(row["correct"] for row in rows),
            "false_resolutions": sum(row["false_resolution"] for row in rows),
            "verdicts": dict(counts),
            "live_model_requests": sum(row["metrics"]["requests"] for row in rows if row["metrics"]["transport"] == "live"),
        },
        "limitations": [
            "Constructed adversarial records, not independently observed provider or customer incidents.",
            "Expected abstention on contradiction is conservative; no assumption identifies which conflicting source is correct.",
            "No payments, wallet transactions, process crashes, or application authorization are exercised by this classification suite.",
            "Repeated runs reuse the same frozen cases and cannot be counted as new holdout cases.",
        ],
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--out", type=Path, default=ROOT / "tmp-runs" / "recovery-holdout.json")
    args = parser.parse_args(argv)
    report = run_holdout(repeats=args.repeats)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Fixture SHA-256: {report['fixture_sha256']}")
    print(f"Wrote {args.out}")
    return int(report["summary"]["correct"] != report["summary"]["samples"])


if __name__ == "__main__":
    raise SystemExit(main())
