#!/usr/bin/env python3
"""Fail if the numbers in the docs disagree with the committed results.

Written after getting this wrong three times by hand. `make all` reruns the
matrix with a fresh draw, the baseline rows shift by a point or two, and the
tables in README.md and FINDINGS.md quietly stop matching the data shipped
alongside them. A reader who checks is entitled to find them consistent.

    python3 experiments/check_docs.py

Exits non-zero on a mismatch and prints exactly which figure is stale.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIMES = ["naive", "replay_position", "replay_content", "anchored"]

# How each runtime is labelled in each document's results table.
LABELS = {
    "FINDINGS.md": {r: f"`{r}`" for r in RUNTIMES},
    "README.md": {
        "naive": "naive retry",
        "replay_position": "replay, position-matched",
        "replay_content": "replay, content-keyed",
        "anchored": "anchored",
    },
}


def ints(row: str) -> list[int]:
    """Every integer in a markdown table row, with $ thousands separators
    collapsed first so `$5,660` reads as 5660 rather than 5 and 660."""
    return [int(x) for x in re.findall(r"\d+", row.replace(",", ""))]


def check(doc: str, data: dict) -> list[str]:
    path = os.path.join(ROOT, doc)
    text = open(path, encoding="utf-8").read()
    problems: list[str] = []

    for rt in RUNTIMES:
        label = LABELS[doc][rt]
        # The results table row: starts with the label, contains "/ 240".
        rows = [
            ln for ln in text.splitlines()
            if ln.strip().startswith("|") and label in ln and "240" in ln
        ]
        if not rows:
            problems.append(f"{doc}: no results row found for {rt}")
            continue

        nums = ints(rows[0])
        e = data["runtimes"][rt]
        want_v, want_t = e["violations"], e["trials"]
        want_paid = data["money"][rt]["total_overpaid_cents"] // 100

        if want_v not in nums or want_t not in nums:
            problems.append(
                f"{doc}: {rt} row says {nums}, findings.json says "
                f"{want_v}/{want_t} violations"
            )
        elif want_paid and want_paid not in nums:
            problems.append(
                f"{doc}: {rt} row says {nums}, findings.json says "
                f"${want_paid:,} overpaid"
            )

    return problems


def check_adjudication() -> list[str]:
    """The same discipline for `results/adjudication.json`.

    Two figures here are not editorial. The validated pipeline's violation
    count must be zero, and the trusting pipeline's must not be, or the
    comparison in FINDINGS.md §8 is not a comparison of anything.
    """
    fp = os.path.join(ROOT, "results", "adjudication.json")
    if not os.path.exists(fp):
        return ["results/adjudication.json missing; run `make adjudication`"]
    data = json.load(open(fp, encoding="utf-8"))
    summary = data["summary"]
    problems: list[str] = []

    validated = summary["by_pipeline"].get("validated", {})
    trusting = summary["by_pipeline"].get("trusting", {})

    if validated.get("false", 0):
        problems.append(
            f"CONTRACT VIOLATED: the validated pipeline produced "
            f"{validated['false']} false resolutions. This is not a docs "
            f"problem; see CONTRACT.md I5."
        )
    if not trusting.get("false", 0):
        problems.append(
            "the trusting control produced no false resolutions, so the "
            "headline comparison in FINDINGS.md §8 demonstrates nothing. "
            "Raise --reps or the agent vice rates."
        )
    if summary["validated"]["resolved"] != summary["validated"][
        "workflow_resumed_committed"
    ]:
        problems.append(
            f"{summary['validated']['resolved']} anchors closed but only "
            f"{summary['validated']['workflow_resumed_committed']} workflows "
            f"resumed; a closed anchor should let the workflow finish"
        )

    # Every figure quoted in the two adjudication tables.
    want = {
        "validated cases": summary["validated"]["cases"],
        "validated closed": summary["validated"]["resolved"],
        "trusting violations": trusting.get("false", 0),
        "trusting closed": trusting.get("resolved", 0),
    }
    for doc in ("FINDINGS.md", "docs/SECOND.md", "README.md"):
        text = open(os.path.join(ROOT, doc), encoding="utf-8").read()
        nums = set(ints(text))
        for label, value in want.items():
            if value not in nums:
                problems.append(f"{doc}: no mention of {label} = {value}")
    return problems


def main() -> int:
    fp = os.path.join(ROOT, "results", "findings.json")
    if not os.path.exists(fp):
        print("results/findings.json missing; run `make analyze` first",
              file=sys.stderr)
        return 1
    data = json.load(open(fp, encoding="utf-8"))

    problems: list[str] = []
    for doc in ("FINDINGS.md", "README.md"):
        problems += check(doc, data)

    # The one figure that must never move.
    a = data["runtimes"]["anchored"]
    if a["violations"] or a["cents_overpaid"]:
        problems.append(
            f"CONTRACT VIOLATED: anchored has {a['violations']} violations and "
            f"{a['cents_overpaid']} cents overpaid. This is not a docs problem."
        )

    problems += check_adjudication()

    if problems:
        print("docs are out of sync with the committed results:\n")
        for p in problems:
            print(f"  {p}")
        print("\nFix the tables, or re-run `make analyze` and update them.")
        return 1

    adj = json.load(
        open(os.path.join(ROOT, "results", "adjudication.json"), encoding="utf-8")
    )["summary"]
    print(
        f"docs consistent with results/ "
        f"({data['n_crashes_confirmed']} confirmed crashes, "
        f"anchored {a['violations']}/{a['trials']} violations; "
        f"{adj['cases']} adjudications, validated "
        f"{adj['by_pipeline']['validated'].get('false', 0)} false)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
