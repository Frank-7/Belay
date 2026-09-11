#!/usr/bin/env python3
"""Turn the raw trial logs into the numbers quoted in FINDINGS.md.

Every figure in the write-up comes out of here, so a reader can check the
prose against the data without re-deriving anything.

    python3 experiments/analyze.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.runtimes import ORDER  # noqa: E402
from experiments.harness import CLEAN, ESCALATED, FAILURES, UNAUTHORIZED  # noqa: E402

RESULTS = os.path.join(ROOT, "results")


def load(name: str) -> dict | None:
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        print(f"missing {path}; run the experiments first", file=sys.stderr)
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    matrix = load("matrix.json")
    revoke = load("revocation.json")
    if not matrix:
        return 1

    trials = [t for t in matrix["trials"] if t["crashed_as_asked"]]
    out: dict = {"n_crashes_confirmed": len(trials), "runtimes": {}}

    for rt in ORDER:
        rows = [t for t in trials if t["runtime"] == rt]
        bad = [t for t in rows if t["verdict"] in FAILURES]
        entry = {
            "trials": len(rows),
            "violations": len(bad),
            "violation_rate": round(len(bad) / len(rows), 4),
            "verdicts": dict(Counter(t["verdict"] for t in rows)),
            "by_tier": {},
            "mean_fsyncs": round(sum(t["fsyncs"] for t in rows) / len(rows), 2),
            "cents_overpaid": sum(
                max(0, t["total_returned_cents"] - 5000) for t in rows
            ),
        }
        for tier in ("idempotent", "queryable", "opaque"):
            sub = [t for t in rows if t["tier"] == tier]
            entry["by_tier"][tier] = {
                "trials": len(sub),
                "violations": sum(1 for t in sub if t["verdict"] in FAILURES),
                "escalated": sum(1 for t in sub if t["verdict"] == ESCALATED),
                "clean": sum(1 for t in sub if t["verdict"] == CLEAN),
            }
        out["runtimes"][rt] = entry

    # Availability cost of `anchored`, split by whether the developer
    # followed the decision-journaling discipline.
    anc = [t for t in trials if t["runtime"] == "anchored"]
    cost: dict = {}
    for jd in (True, False):
        sub = [t for t in anc if t["journal_decision"] is jd]
        by_tier = {}
        for tier in ("idempotent", "queryable", "opaque"):
            s2 = [t for t in sub if t["tier"] == tier]
            esc = [t for t in s2 if t["verdict"] == ESCALATED]
            by_tier[tier] = {
                "trials": len(s2),
                "escalated": len(esc),
                "escalation_rate": round(len(esc) / len(s2), 4) if s2 else None,
                # An escalation where nothing actually committed is a page
                # for a non-event. Irreducible on the opaque tier, because
                # "never sent" and "sent, ack lost" are the same observation.
                "escalations_with_no_effect": sum(1 for t in esc if t["n_refunds"] == 0),
            }
        cost["journaled" if jd else "inline"] = by_tier
    out["anchored_availability_cost"] = cost

    # Money. The order is 5000 cents; anything else is an error with a
    # dollar sign attached.
    money = {}
    for rt in ORDER:
        rows = [t for t in trials if t["runtime"] == rt]
        over = [t["total_returned_cents"] - 5000 for t in rows]
        money[rt] = {
            "trials": len(rows),
            "trials_overpaid": sum(1 for x in over if x > 0),
            "total_overpaid_cents": sum(x for x in over if x > 0),
            "worst_single_overpay_cents": max(over) if over else 0,
            "trials_books_wrong": sum(
                1 for t in rows if t["verdict"] == "misattributed"
            ),
        }
    out["money"] = money

    if revoke:
        rv = [t for t in revoke["trials"] if t["crashed_as_asked"]]
        out["revocation"] = {
            rt: {
                "trials": len([t for t in rv if t["runtime"] == rt]),
                "unauthorized": len(
                    [
                        t
                        for t in rv
                        if t["runtime"] == rt and t["verdict"] == UNAUTHORIZED
                    ]
                ),
            }
            for rt in ORDER
        }

    path = os.path.join(RESULTS, "findings.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    # --- printed summary ---
    print(f"confirmed crashes analysed: {out['n_crashes_confirmed']}\n")
    print("HEADLINE")
    for rt in ORDER:
        e = out["runtimes"][rt]
        print(
            f"  {rt:<18} {e['violations']:>4}/{e['trials']} violations "
            f"({e['violation_rate']:.1%})"
        )
    print("\nMONEY (order value 5000 cents per trial)")
    for rt in ORDER:
        m = out["money"][rt]
        print(
            f"  {rt:<18} overpaid in {m['trials_overpaid']:>3} trials, "
            f"{m['total_overpaid_cents']:>6} cents total, "
            f"books wrong in {m['trials_books_wrong']:>2}"
        )
    print("\nANCHORED AVAILABILITY COST (escalation rate)")
    for mode, tiers in out["anchored_availability_cost"].items():
        bits = " ".join(
            f"{t}={v['escalation_rate']:.0%}" for t, v in tiers.items()
        )
        print(f"  discipline={mode:<10} {bits}")
    op = out["anchored_availability_cost"]["journaled"]["opaque"]
    print(
        f"\n  On the opaque tier under the sound discipline: "
        f"{op['escalated']}/{op['trials']} escalated, of which "
        f"{op['escalations_with_no_effect']} were pages for an effect that "
        f"never committed."
    )
    if revoke:
        print("\nREVOCATION (refunds issued after the scope was pulled)")
        for rt in ORDER:
            r = out["revocation"][rt]
            print(f"  {rt:<18} {r['unauthorized']}/{r['trials']}")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
