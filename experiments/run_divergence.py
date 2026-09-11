#!/usr/bin/env python3
"""The mechanism, shown one trial at a time.

`run_matrix.py` gives rates. This gives the causal story, with the agent's
decision pinned so the divergence happens on demand rather than by chance:

    first pass  -> full_refund  (5000, no credit)
    recovery    -> split_refund (3000 + 2000 credit)

Order value is 5000 cents. Anything other than exactly 5000 leaving the
ledger is a bug with a dollar sign on it.

    python3 experiments/run_divergence.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.runtimes import ORDER  # noqa: E402
from experiments.harness import run_trial  # noqa: E402

EXPLAIN = {
    "naive": "no durable intent, so recovery can only re-run the whole thing",
    "replay_position": "journaled receipt claimed by a step that is no longer the same step",
    "replay_content": "key is derived from the decision, so a diverged decision changes the key",
    "anchored": "anchor was allocated before the decision, so divergence cannot move it",
}


def scenario(title: str, **kw) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    base = tempfile.mkdtemp(prefix="belay-div-")
    print(
        f"{'runtime':<18}{'verdict':<18}{'refunds (cents)':<20}"
        f"{'reported':<11}total out"
    )
    print("-" * 78)
    for rt in ORDER:
        t = run_trial(base, runtime=rt, **kw)
        total = t.total_returned_cents
        flag = "" if total == 5000 else f"  <-- {total - 5000:+d} vs order value"
        print(
            f"{rt:<18}{t.verdict:<18}{str(t.refund_amounts):<20}"
            f"{str(t.reported_refund):<11}{total}{flag}"
        )
    print()
    for rt in ORDER:
        print(f"  {rt:<18} {EXPLAIN[rt]}")


def main() -> int:
    print(__doc__)

    scenario(
        "A. Crash in flight. Decision NOT persisted before it was used.\n"
        "   Service tier: idempotent (the best tier available).",
        tier="idempotent",
        crash_at="in_flight",
        journal_decision=False,
        force_plans=("full_refund", "split_refund_plus_credit"),
    )
    print(
        "\n  Read that again: the payment service offers idempotency keys and\n"
        "  the replay runtime supplies one. It still double-refunds, because\n"
        "  the key it supplies is a hash of an amount the model chose, and on\n"
        "  recovery the model chose differently."
    )

    scenario(
        "B. Same crash, same tier, decision persisted first (sound discipline).",
        tier="idempotent",
        crash_at="in_flight",
        journal_decision=True,
        force_plans=("full_refund", "split_refund_plus_credit"),
    )
    print(
        "\n  Both replay runtimes are correct here. This is the important\n"
        "  control: replay is not broken. It is correct under a discipline\n"
        "  that no framework enforces and no test surfaces."
    )

    scenario(
        "C. Crash after effect A is fully durable, decision not persisted.\n"
        "   The two replay strategies now fail in different directions.",
        tier="idempotent",
        crash_at="after_effect_a_recorded",
        journal_decision=False,
        force_plans=("full_refund", "split_refund_plus_credit"),
    )
    print(
        "\n  replay_position keeps the books wrong rather than the money wrong:\n"
        "  one refund of 5000 committed, reported to the operator as 3000.\n"
        "  No alert fires. Reconciliation finds it next month."
    )

    scenario(
        "D. Crash in flight against a service with no idempotency and no\n"
        "   lookup. Nobody can be correct here; the question is who admits it.",
        tier="opaque",
        crash_at="in_flight",
        journal_decision=True,
        force_plans=("full_refund", "full_refund"),
    )
    print(
        "\n  `anchored` escalates. It has resolved nothing and claims nothing.\n"
        "  That is the only defensible answer: the effect's status is not\n"
        "  recoverable from anything the service will tell us."
    )

    print("\n" + "=" * 78)
    print("Journal from scenario A, `anchored`, annotated")
    print("=" * 78)
    dump_journal()
    return 0


def dump_journal() -> None:
    import json

    base = tempfile.mkdtemp(prefix="belay-dump-")
    run_trial(
        base,
        runtime="anchored",
        tier="idempotent",
        crash_at="in_flight",
        journal_decision=False,
        force_plans=("full_refund", "split_refund_plus_credit"),
        keep=True,
    )
    run_dir = next(
        os.path.join(base, d) for d in os.listdir(base) if d.startswith("anchored")
    )
    notes = {
        "anchor": "effect identity, fsynced BEFORE the model is called",
        "attempt_start": "process boundary",
        "intent": "about to call the service, under this anchor, for this amount",
        "resolved": "ambiguity settled against the service using the anchor",
        "escalated": "halted; a human is needed",
        "settled": "service confirmed, durably recorded",
    }
    with open(os.path.join(run_dir, "journal.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            k = r["kind"]
            detail = {
                x: r[x]
                for x in ("slot", "anchor", "amount", "method", "replaying", "reason")
                if x in r
            }
            if "anchor" in detail:
                detail["anchor"] = detail["anchor"][:8]
            if "reason" in detail:
                detail["reason"] = detail["reason"][:44] + "..."
            print(f"  pid={r['pid']}  {k:<16} {detail}")
            if k in notes:
                print(f"{'':>22}   ^ {notes[k]}")


if __name__ == "__main__":
    raise SystemExit(main())
