"""Regressions for torn journals and interrupted anchor allocation.

Run standalone, or through make test. Payment assertions use the existing
ledger API as an external oracle; these tests never inspect its source.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from belay.agent import PLAN_SPLIT  # noqa: E402
from belay.journal import Journal  # noqa: E402
from belay.runtimes.base import Ctx  # noqa: E402

ORDER = "order-anchor-regression"
TORN = b'{"seq":1,"kind":"dec'

# Kill a real child after the first anchor has been fsynced, before the
# second append. Production crash points and runtime source stay unchanged.
CRASH_AFTER_ANCHOR = """
import os, signal, sys
from unittest.mock import patch
from belay.journal import Journal
from belay.runtimes import anchored
from belay.runtimes.base import Ctx
ctx = Ctx(sys.argv[1], "crashed", "order-anchor-regression", sys.argv[2])
ctx.perms.grant_all(["payments:refund", "credits:issue"])
append = Journal.append
def crash_after_append(self, kind, **payload):
    record = append(self, kind, **payload)
    if kind == "anchor" and payload["slot"] == sys.argv[3]:
        os.kill(os.getpid(), signal.SIGKILL)
    return record
with patch.object(Journal, "append", crash_after_append):
    getattr(anchored, sys.argv[4])(ctx)
"""


class JournalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-journal-regression-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "journal.jsonl"
        self.journal = Journal(str(self.path), "r1")
        self.anchor = self.journal.append("anchor", slot="refund")
        self.prefix = self.path.read_bytes()

    def add_tail(self, tail):
        with self.path.open("ab") as fh:
            fh.write(tail)

    def test_torn_tail_then_successful_append_is_readable(self):
        self.add_tail(TORN)
        reopened = Journal(str(self.path), "r2")
        decided = reopened.append("decided", plan="full")
        self.assertEqual(Journal(str(self.path), "r3").read(), [self.anchor, decided])
        self.assertEqual(decided["seq"], 1)

    def test_interior_corruption_raises_at_open_without_truncating(self):
        self.add_tail(TORN + b'\n{"seq":2,"kind":"decided","plan":"full"}\n')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "interior corruption"):
            Journal(str(self.path), "r2")
        self.assertEqual(self.path.read_bytes(), before)

    def test_read_rejects_interior_corruption_without_truncating(self):
        self.add_tail(TORN + b'\n{"seq":2,"kind":"decided","plan":"full"}\n')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "interior corruption"):
            self.journal.read()
        self.assertEqual(self.path.read_bytes(), before)

    def test_partial_utf8_tail_can_be_repaired(self):
        self.add_tail(b'{"kind":"decided","note":"\xe2\x82')
        reopened = Journal(str(self.path), "r2")
        decided = reopened.append("decided", plan="full")
        self.assertEqual(reopened.read(), [self.anchor, decided])

    def test_invalid_utf8_before_a_good_record_raises(self):
        self.add_tail(b'\xff\n{"seq":2,"kind":"decided"}\n')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "interior corruption"):
            Journal(str(self.path), "r2")
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_record_delimiter_is_a_torn_tail(self):
        self.add_tail(b'{"seq":1,"kind":"decided","plan":"uncommitted"}')
        reopened = Journal(str(self.path), "r2")
        decided = reopened.append("decided", plan="full")
        self.assertEqual(reopened.read(), [self.anchor, decided])
        self.assertEqual(decided["seq"], 1)

    def test_tail_repair_is_fsynced_before_new_appends(self):
        self.add_tail(TORN)
        real_fsync = os.fsync
        sizes_at_sync = []

        def fsync(fd):
            sizes_at_sync.append(os.fstat(fd).st_size)
            return real_fsync(fd)

        with patch("belay.journal.os.fsync", side_effect=fsync):
            reopened = Journal(str(self.path), "r2")
        self.assertEqual(self.path.read_bytes(), self.prefix)
        self.assertEqual(sizes_at_sync, [len(self.prefix)])
        self.assertEqual(reopened.fsync_count, 1)

    def test_healthy_reopen_preserves_records_and_observe_sidecar(self):
        self.journal.observe("inline_decision", plan="split", durable=False)
        trace = self.path.with_name("trace.jsonl")
        trace_before = trace.read_bytes()
        reopened = Journal(str(self.path), "r2")
        self.assertEqual(reopened.read(), [self.anchor])
        self.assertEqual(self.path.read_bytes(), self.prefix)
        self.assertEqual(trace.read_bytes(), trace_before)
        self.assertEqual(reopened.fsync_count, 0)
        reopened.observe("recovered", diagnostic=True)
        self.assertEqual(reopened.fsync_count, 0)
        self.assertEqual(reopened.read(), [self.anchor])
        observations = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertEqual([r["kind"] for r in observations], ["inline_decision", "recovered"])

    def test_short_writes_finish_the_record_before_returning(self):
        real_write = os.write
        with patch("belay.journal.os.write", side_effect=lambda fd, data: real_write(fd, data[:7])):
            decided = self.journal.append("decided", plan="full")
        self.assertEqual(self.journal.read(), [self.anchor, decided])
        self.assertEqual(self.journal.fsync_count, 2)

    def test_failed_write_requires_reopen_before_appending(self):
        real_write = os.write
        calls = 0

        def stall_after_prefix(fd, data):
            nonlocal calls
            calls += 1
            return real_write(fd, data[:7]) if calls == 1 else 0

        with patch("belay.journal.os.write", side_effect=stall_after_prefix):
            with self.assertRaises(OSError):
                self.journal.append("decided", plan="incomplete")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "reopen"):
            self.journal.append("decided", plan="must not append past damage")
        self.assertEqual(self.path.read_bytes(), before)
        reopened = Journal(str(self.path), "r2")
        decided = reopened.append("decided", plan="full")
        self.assertEqual(reopened.read(), [self.anchor, decided])


class AnchorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-anchor-regression-")
        self.addCleanup(self.directory.cleanup)

    def context(self, run_dir, tier="idempotent"):
        ctx = Ctx(str(run_dir), "fixture", ORDER, tier)
        ctx.perms.grant_all(["payments:refund", "credits:issue"])
        return ctx

    def child_env(self, run_dir, tier, plan):
        return {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
                "BELAY_RUN_DIR": str(run_dir), "BELAY_RUN_ID": "recovered",
                "BELAY_RUNTIME": "anchored", "BELAY_MODE": "recover",
                "BELAY_TIER": tier, "BELAY_ORDER_ID": ORDER,
                "BELAY_CRASH_AT": "none", "BELAY_FORCE_PLAN": plan,
                "BELAY_JOURNAL_DECISION": "1"}

    def crash(self, run_dir, tier, slot="refund", mode="run"):
        result = subprocess.run(
            [sys.executable, "-c", CRASH_AFTER_ANCHOR, str(run_dir), tier, slot, mode],
            cwd=ROOT, env=self.child_env(run_dir, tier, PLAN_SPLIT.label),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)

    def recover(self, run_dir, tier="idempotent", plan=PLAN_SPLIT.label):
        process = subprocess.run(
            [sys.executable, str(ROOT / "worker.py")], cwd=ROOT,
            env=self.child_env(run_dir, tier, plan),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        outcome = json.loads((run_dir / "outcome.recover.json").read_text())
        ctx = Ctx(str(run_dir), "inspect", ORDER, tier)
        try:
            rows = [dict(row) for row in ctx.ledger.for_order(ORDER)]
        finally:
            ctx.ledger.close()
        return outcome, rows, ctx.journal.read()

    def assert_complete(self, outcome, rows):
        observed = f"outcome={outcome}; ledger={rows}"
        self.assertEqual(outcome["status"], "committed", observed)
        self.assertEqual(outcome["plan_label"], PLAN_SPLIT.label)
        self.assertEqual(outcome["reported_refund_cents"], 3000)
        self.assertEqual(outcome["reported_credit_cents"], 2000)
        self.assertEqual(sum(r["amount_cents"] for r in rows), 5000, observed)
        self.assertEqual(sorted((r["service"], r["amount_cents"]) for r in rows),
                         [("credits", 2000), ("payments", 3000)])

    def test_partial_allocation_with_persisted_split_decision(self):
        for tier in ("idempotent", "queryable", "opaque"):
            with self.subTest(tier=tier):
                run_dir = Path(self.directory.name) / tier
                self.crash(run_dir, tier)
                journal = Journal(str(run_dir / "journal.jsonl"), "persisted-plan-fixture")
                anchors = journal.of_kind("anchor")
                self.assertEqual([r["slot"] for r in anchors], ["refund"])
                # The review's constructed persisted-decision reproduction.
                # A natural crash at this point has no decision; tested below.
                journal.append("decided", plan=PLAN_SPLIT.as_dict())
                outcome, rows, records = self.recover(run_dir, tier, "full_refund")
                self.assert_complete(outcome, rows)
                final_anchors = [r for r in records if r["kind"] == "anchor"]
                self.assertEqual(final_anchors[0], anchors[0])
                self.assertEqual([r["slot"] for r in final_anchors], ["refund", "credit"])
                self.assertTrue(final_anchors[1]["allocation_recovered"])
                credit_index = records.index(final_anchors[1])
                self.assertLess(credit_index, next(i for i, r in enumerate(records) if r["kind"] == "intent"))
                again, later_rows, later_records = self.recover(run_dir, tier, "full_refund")
                self.assert_complete(again, later_rows)
                self.assertEqual([r for r in later_records if r["kind"] == "anchor"], final_anchors)

    def test_real_crash_before_decision_completes_allocation_first(self):
        run_dir = Path(self.directory.name)
        self.crash(run_dir, "idempotent")
        journal = Journal(str(run_dir / "journal.jsonl"), "inspect")
        self.assertFalse(journal.of_kind("decided"))
        outcome, rows, records = self.recover(run_dir)
        self.assert_complete(outcome, rows)
        last_anchor = max(i for i, r in enumerate(records) if r["kind"] == "anchor")
        first_decision = next(i for i, r in enumerate(records) if r["kind"] == "decided")
        self.assertLess(last_anchor, first_decision)

    def test_crash_during_completed_allocation_does_not_remint(self):
        run_dir = Path(self.directory.name)
        self.crash(run_dir, "idempotent")
        self.crash(run_dir, "idempotent", slot="credit", mode="recover")
        journal = Journal(str(run_dir / "journal.jsonl"), "inspect")
        allocated = journal.of_kind("anchor")
        self.assertEqual([r["slot"] for r in allocated], ["refund", "credit"])
        self.assertFalse(journal.of_kind("intent"))
        outcome, rows, records = self.recover(run_dir)
        self.assert_complete(outcome, rows)
        self.assertEqual([r for r in records if r["kind"] == "anchor"], allocated)

    def test_escalated_state_does_not_allocate_or_move_money(self):
        run_dir = Path(self.directory.name)
        ctx = self.context(run_dir)
        ctx.journal.append("anchor", slot="refund", anchor="existing-refund")
        ctx.journal.append("escalated", slot="refund", reason="unresolved")
        ctx.ledger.close()
        outcome, rows, records = self.recover(run_dir)
        self.assertEqual(outcome["status"], "escalated")
        self.assertEqual(rows, [])
        self.assertEqual([r["slot"] for r in records if r["kind"] == "anchor"], ["refund"])

    def test_effect_record_without_anchor_is_rejected_before_allocation(self):
        for kind in ("intent", "settled"):
            with self.subTest(kind=kind):
                run_dir = Path(self.directory.name) / kind
                ctx = self.context(run_dir)
                ctx.journal.append("anchor", slot="refund", anchor="existing-refund")
                ctx.journal.append("decided", plan=PLAN_SPLIT.as_dict())
                ctx.journal.append(kind, slot="credit", anchor="orphan-credit", amount=2000)
                ctx.ledger.close()
                outcome, rows, records = self.recover(run_dir)
                self.assertEqual(outcome["status"], "escalated", outcome)
                self.assertEqual(rows, [])
                self.assertEqual([r["slot"] for r in records if r["kind"] == "anchor"], ["refund"])


def run_regressions():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


if __name__ == "__main__":
    unittest.main(verbosity=2)
