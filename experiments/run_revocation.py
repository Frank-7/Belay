#!/usr/bin/env python3
"""Invariant 2: authorisation must hold at execution time, not plan time.

The scenario is mundane and happens constantly in production: an agent
plans an action, the process dies, an operator revokes the agent's refund
scope while it is down, and then it comes back up.

A replay runtime that journaled its authorisation check as an activity
result will replay the check as a settled fact and execute anyway. That is
not a bug in the framework; it is the framework doing exactly what it
promises, applied to a fact that was never safe to treat as deterministic.

    python3 experiments/run_revocation.py --reps 8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.runtimes import ORDER  # noqa: E402
from experiments.harness import UNAUTHORIZED, run_trial  # noqa: E402

# Crash points that leave the workflow with the refund still to perform.
POINTS = ["after_decide_before_journal", "after_intent"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "revocation.json"))
    args = ap.parse_args()

    print(__doc__)
    base = tempfile.mkdtemp(prefix="belay-revoke-")
    trials = []

    for rt in ORDER:
        for crash in POINTS:
            for _ in range(args.reps):
                trials.append(
                    run_trial(
                        base,
                        runtime=rt,
                        tier="idempotent",
                        crash_at=crash,
                        revoke_scope="payments:refund",
                    ).as_dict()
                )

    print("=" * 72)
    print("REFUNDS ISSUED AFTER THE SCOPE WAS REVOKED")
    print("=" * 72)
    print(f"{'runtime':<18}{'trials':>8}{'unauthorised':>14}{'rate':>8}   verdicts")
    print("-" * 72)
    for rt in ORDER:
        rows = [t for t in trials if t["runtime"] == rt and t["crashed_as_asked"]]
        bad = [t for t in rows if t["verdict"] == UNAUTHORIZED]
        mix = ", ".join(f"{k}={v}" for k, v in Counter(t["verdict"] for t in rows).items())
        rate = len(bad) / len(rows) if rows else 0
        print(f"{rt:<18}{len(rows):>8}{len(bad):>14}{rate:>7.0%}   {mix}")

    print(
        "\n`naive` scores well here for an uninteresting reason: it has no\n"
        "journal, so it re-checks the permission on every attempt. It buys\n"
        "authorisation freshness with the duplicate-effect rate measured in\n"
        "run_matrix.py. It is not a safe design, just differently unsafe.\n"
    )
    print(
        "`anchored` refuses because the check is a live read taken in the\n"
        "same breath as the call, and is never written to the journal as a\n"
        "replayable fact. Nothing about the mechanism is clever. The point is\n"
        "that authorisation is not the kind of thing a journal can remember\n"
        "on your behalf."
    )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"trials": trials}, fh, indent=2)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
