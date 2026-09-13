#!/usr/bin/env python3
"""Assertions on the correctness contract, runnable in a few seconds.

These are not unit tests of helper functions. Each one asserts an invariant
from CONTRACT.md under a real SIGKILL, so a regression in the runtime shows
up as a failing invariant rather than a failing mock.

    python3 tests/test_contract.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from test_runtime_recovery import run_regressions  # noqa: E402

from belay.chaos import CRASH_POINTS  # noqa: E402
from belay.runtimes import ORDER  # noqa: E402
from experiments.harness import FAILURES, run_trial  # noqa: E402

TIERS = ["idempotent", "queryable", "opaque"]
ORDER_VALUE = 5000

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


def test_crashes_land_where_asked(base: str) -> None:
    print("\nthe harness crashes at the instruction it was told to")
    for point in CRASH_POINTS:
        if point == "none":
            continue
        t = run_trial(base, "anchored", "idempotent", point)
        expected = point != "after_anchor" or True
        check(
            f"crash at {point}",
            t.crashed_as_asked == expected,
            f"crashed_as_asked={t.crashed_as_asked}",
        )


def test_invariant_1_no_duplicate_effects(base: str) -> None:
    print("\ninvariant 1: at most one committed refund per workflow")
    for tier in TIERS:
        for point in ("after_intent", "in_flight", "after_ack_before_record"):
            for journaled in (True, False):
                t = run_trial(
                    base, "anchored", tier, point, journal_decision=journaled
                )
                check(
                    f"anchored/{tier}/{point}/journaled={journaled}",
                    t.n_refunds <= 1,
                    f"ledger={t.refund_amounts}",
                )


def test_invariant_1_baselines_do_violate_it(base: str) -> None:
    print("\ninvariant 1 is not trivially satisfiable: baselines violate it")
    violations = 0
    for rt in ORDER:
        if rt == "anchored":
            continue
        for _ in range(4):
            t = run_trial(base, rt, "opaque", "in_flight")
            if t.verdict in FAILURES:
                violations += 1
    check(
        "at least one baseline violation observed",
        violations > 0,
        f"saw {violations}; if zero, the harness is not exercising the window",
    )


def test_invariant_2_authorization_is_live(base: str) -> None:
    print("\ninvariant 2: no effect issued under a revoked scope")
    for point in ("after_decide_before_journal", "after_intent"):
        t = run_trial(
            base, "anchored", "idempotent", point, revoke_scope="payments:refund"
        )
        check(
            f"anchored refuses after revocation at {point}",
            t.verdict != "unauthorized_effect",
            f"verdict={t.verdict} ledger={t.refund_amounts}",
        )


def test_invariant_3_ambiguity_is_escalated(base: str) -> None:
    print("\ninvariant 3: unresolvable ambiguity halts instead of guessing")
    t = run_trial(base, "anchored", "opaque", "in_flight")
    check(
        "opaque tier, lost ack, anchored escalates",
        t.verdict == "escalated",
        f"verdict={t.verdict}",
    )
    check(
        "and the single committed effect is left intact",
        t.n_refunds == 1,
        f"ledger={t.refund_amounts}",
    )


def test_reports_never_exceed_reality(base: str) -> None:
    print("\nanchored never reports an outcome the ledger contradicts")
    for tier in TIERS:
        for point in ("in_flight", "after_ack_before_record", "after_effect_a_recorded"):
            t = run_trial(base, "anchored", tier, point)
            if t.reported_status != "committed":
                continue
            check(
                f"report matches ledger {tier}/{point}",
                t.reported_refund == sum(t.refund_amounts),
                f"reported={t.reported_refund} ledger={t.refund_amounts}",
            )


def test_no_money_created(base: str) -> None:
    print("\nanchored never moves more than the order value")
    for tier in TIERS:
        for journaled in (True, False):
            t = run_trial(
                base, "anchored", tier, "in_flight", journal_decision=journaled
            )
            check(
                f"total refunded <= order value {tier}/journaled={journaled}",
                t.total_returned_cents <= ORDER_VALUE,
                f"ledger={t.refund_amounts}",
            )


def main() -> int:
    base = tempfile.mkdtemp(prefix="belay-tests-")
    test_crashes_land_where_asked(base)
    test_invariant_1_no_duplicate_effects(base)
    test_invariant_1_baselines_do_violate_it(base)
    test_invariant_2_authorization_is_live(base)
    test_invariant_3_ambiguity_is_escalated(base)
    test_reports_never_exceed_reality(base)
    test_no_money_created(base)

    print(f"\n{_passed} passed, {len(_failed)} failed")
    for f in _failed:
        print(f"  {f}")
    regressions_passed = run_regressions()
    return 1 if _failed or not regressions_passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
