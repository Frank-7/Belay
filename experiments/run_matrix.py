#!/usr/bin/env python3
"""The crash matrix.

4 runtimes x 3 service tiers x 5 crash points x 2 discipline settings,
repeated with the agent's nondeterminism left switched on. Every cell is
graded against the ledger, not against the runtime's own report.

    python3 experiments/run_matrix.py --reps 8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.runtimes import ORDER  # noqa: E402
from experiments.harness import (  # noqa: E402
    CLEAN,
    ESCALATED,
    FAILURES,
    LOST,
    REFUSED,
    run_trial,
)

TIERS = ["idempotent", "queryable", "opaque"]

# The five crash points every runtime passes through. `after_anchor` is
# excluded because only `anchored` has that instruction, and a crash point
# that never fires for three of the four runtimes would not be a fair cell.
CRASH_POINTS = [
    "after_decide_before_journal",
    "after_intent",
    "in_flight",
    "after_ack_before_record",
    "after_effect_a_recorded",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--nondet-p", type=float, default=0.5)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "matrix.json"))
    args = ap.parse_args()

    cells = [
        (rt, tier, crash, journaled, rep)
        for rt in ORDER
        for tier in TIERS
        for crash in CRASH_POINTS
        for journaled in (True, False)
        for rep in range(args.reps)
    ]
    print(
        f"{len(cells)} trials: {len(ORDER)} runtimes x {len(TIERS)} tiers x "
        f"{len(CRASH_POINTS)} crash points x 2 disciplines x {args.reps} reps"
    )

    base = tempfile.mkdtemp(prefix="belay-matrix-")
    results = []

    def work(cell):
        rt, tier, crash, journaled, _rep = cell
        return run_trial(
            base,
            runtime=rt,
            tier=tier,
            crash_at=crash,
            nondet_p=args.nondet_p,
            journal_decision=journaled,
        )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, trial in enumerate(pool.map(work, cells), 1):
            results.append(trial.as_dict())
            if i % 100 == 0:
                print(f"  {i}/{len(cells)}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "config": {
                    "reps": args.reps,
                    "nondet_p": args.nondet_p,
                    "tiers": TIERS,
                    "crash_points": CRASH_POINTS,
                    "runtimes": ORDER,
                },
                "trials": results,
            },
            fh,
            indent=2,
        )
    print(f"\nwrote {args.out}")
    report(results)
    return 0


def report(trials: list[dict]) -> None:
    confirmed = [t for t in trials if t["crashed_as_asked"]]
    print(
        f"\n{len(confirmed)}/{len(trials)} trials crashed at the requested "
        f"instruction; the rest never reached it and are excluded."
    )

    print("\n" + "=" * 74)
    print("CONTRACT VIOLATIONS BY RUNTIME  (lower is better)")
    print("=" * 74)
    hdr = f"{'runtime':<18}{'trials':>8}{'violations':>12}{'rate':>9}{'escalated':>11}{'clean':>8}"
    print(hdr)
    print("-" * 74)
    for rt in ORDER:
        rows = [t for t in confirmed if t["runtime"] == rt]
        bad = [t for t in rows if t["verdict"] in FAILURES]
        esc = [t for t in rows if t["verdict"] == ESCALATED]
        cln = [t for t in rows if t["verdict"] == CLEAN]
        rate = len(bad) / len(rows) if rows else 0
        print(
            f"{rt:<18}{len(rows):>8}{len(bad):>12}{rate:>8.1%}"
            f"{len(esc):>11}{len(cln):>8}"
        )

    print("\n" + "=" * 74)
    print("VIOLATION RATE BY SERVICE TIER")
    print("=" * 74)
    print(f"{'runtime':<18}" + "".join(f"{t:>18}" for t in TIERS))
    print("-" * 74)
    for rt in ORDER:
        cells = []
        for tier in TIERS:
            rows = [
                t for t in confirmed if t["runtime"] == rt and t["tier"] == tier
            ]
            bad = sum(1 for t in rows if t["verdict"] in FAILURES)
            cells.append(f"{bad}/{len(rows)}" if rows else "-")
        print(f"{rt:<18}" + "".join(f"{c:>18}" for c in cells))

    print("\n" + "=" * 74)
    print("EFFECT OF THE DECISION-JOURNALING DISCIPLINE")
    print("  journaled=True  : model call is an activity, result persisted first")
    print("  journaled=False : model call sits in workflow code, not persisted")
    print("=" * 74)
    print(f"{'runtime':<18}{'journaled':>14}{'inline':>14}")
    print("-" * 74)
    for rt in ORDER:
        cells = []
        for jd in (True, False):
            rows = [
                t
                for t in confirmed
                if t["runtime"] == rt and t["journal_decision"] is jd
            ]
            bad = sum(1 for t in rows if t["verdict"] in FAILURES)
            cells.append(f"{bad}/{len(rows)}" if rows else "-")
        print(f"{rt:<18}{cells[0]:>14}{cells[1]:>14}")

    print("\n" + "=" * 74)
    print("VERDICT BREAKDOWN")
    print("=" * 74)
    per = defaultdict(Counter)
    for t in confirmed:
        per[t["runtime"]][t["verdict"]] += 1
    kinds = sorted({v for c in per.values() for v in c})
    print(f"{'runtime':<18}" + "".join(f"{k[:11]:>13}" for k in kinds))
    print("-" * 74)
    for rt in ORDER:
        print(f"{rt:<18}" + "".join(f"{per[rt].get(k, 0):>13}" for k in kinds))

    print("\n" + "=" * 74)
    print("COST OF THE GUARANTEE")
    print("=" * 74)
    print(f"{'runtime':<18}{'mean fsyncs':>14}{'mean recovery ms':>19}{'escalation rate':>18}")
    print("-" * 74)
    for rt in ORDER:
        rows = [t for t in confirmed if t["runtime"] == rt]
        if not rows:
            continue
        fs = sum(t["fsyncs"] for t in rows) / len(rows)
        rms = [t["recovery_ms"] for t in rows if t["recovery_ms"]]
        ms = sum(rms) / len(rms) if rms else 0
        esc = sum(1 for t in rows if t["verdict"] == ESCALATED) / len(rows)
        print(f"{rt:<18}{fs:>14.1f}{ms:>19.1f}{esc:>17.1%}")

    unfinished = [t for t in confirmed if t["verdict"] in (ESCALATED, REFUSED, LOST)]
    print(
        f"\nSafe-but-unfinished outcomes across all runtimes: {len(unfinished)}"
        f"/{len(confirmed)}. These are the availability cost of refusing to guess."
    )


if __name__ == "__main__":
    raise SystemExit(main())
