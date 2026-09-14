"""Operator workflow, restart, wallet identity and HTTP boundaries (offline)."""

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recovery_app.arc import (  # noqa: E402
    CHAIN_HEX,
    TOKEN_ADDRESS,
    ArcEvidenceProvider,
    transfer_data,
)
from recovery_app.engine import AppError, Engine  # noqa: E402
from recovery_app.server import make_server  # noqa: E402

SENDER = "0x" + "12" * 20
RECIPIENT = "0x" + "34" * 20
HASH = "0x" + "56" * 32


class FinalizedRevert(ArcEvidenceProvider):
    """Exercise the real Arc verifier with an offline, mutable chain fixture."""

    def __init__(self):
        super().__init__(self.rpc)
        self.finalized = 102
        self.block_hash = "0x" + "78" * 32
        self.available = True
        self.calls = []

    def rpc(self, method, params):
        self.calls.append(method)
        if method == "eth_chainId":
            return CHAIN_HEX
        if method == "eth_getBlockByNumber":
            if params[0] == "latest":
                return {"number": "0x64", "hash": "0x" + "ab" * 32}
            if params[0] == "finalized":
                return {"number": hex(self.finalized), "hash": "0x" + "cd" * 32}
            return {"number": "0x65", "hash": self.block_hash}
        common = {"from": SENDER, "to": TOKEN_ADDRESS, "blockNumber": "0x65", "blockHash": self.block_hash}
        if method == "eth_getTransactionByHash":
            return {**common, "hash": HASH, "chainId": CHAIN_HEX, "value": "0x0",
                    "input": transfer_data(RECIPIENT, 10_000)}
        if method == "eth_getTransactionReceipt":
            return {**common, "transactionHash": HASH, "status": "0x0", "logs": [],
                    "gasUsed": "0x5208", "effectiveGasPrice": "0x1"} if self.available else None
        raise AssertionError("Unexpected RPC method: " + method)


class FakeArc:
    def __init__(self):
        self.status = "committed"
        self.calls = []

    def head(self):
        return {"block_number": 100, "chain_id": 5042002}

    def read(self, expected):
        self.calls.append(dict(expected))
        status = self.status if expected.get("transaction_hash") else "unknown"
        return {"status": status, "reason": status, "metadata": {"chain_id": 5042002}, "raw": {},
                "records": [{"transaction_hash": expected["transaction_hash"], "amount_units": expected["amount_units"]}]
                if status == "committed" else []}


class RecoveryAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.arc = FakeArc()
        self.engine = Engine(self.directory.name, arc_provider=self.arc)

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def investigate(self, scenario):
        incident = self.engine.create(scenario)
        return self.engine.investigate(incident["id"], "heuristic")

    def wallet(self):
        return self.engine.prepare_wallet(SENDER, RECIPIENT, 10_000)

    def test_lost_ack_closes_from_evidence_without_another_payment(self):
        incident = self.investigate("lost_ack")
        self.assertEqual(incident["proposal"]["verdict"], "committed")
        final = self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(final["status"], "resolved")
        self.assertEqual(len(self.engine._simulation_records(final)), 1)
        with self.assertRaises(AppError):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(len(self.engine._simulation_records(final)), 1)

    def test_confirmed_absence_completes_exact_original_amount(self):
        incident = self.investigate("never_sent")
        self.assertEqual(incident["proposal"]["verdict"], "absent")
        final = self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(final["outcome"]["action"], "completed")
        self.assertEqual([row["amount_cents"] for row in self.engine._simulation_records(final)], [5000])

    def test_revocation_after_proposal_prevents_completion(self):
        incident = self.investigate("never_sent")
        self.engine.revoke(incident["id"])
        final = self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(final["status"], "refused")
        self.assertEqual(self.engine._simulation_records(final), [])

    def test_stale_report_requires_probe_and_new_proposal(self):
        incident = self.investigate("stale_report")
        self.assertEqual(incident["proposal"]["verdict"], "abstain")
        self.assertEqual(incident["next_steps"][0]["action"], "probe")
        self.engine.probe(incident["id"])
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.assertEqual(incident["proposal"]["verdict"], "committed")

    def test_conflict_requires_reconciliation_not_model_confidence(self):
        incident = self.investigate("conflicting_sources")
        self.assertEqual(incident["proposal"]["verdict"], "abstain")
        self.assertIn("conflict", " ".join(incident["proposal"]["validator_notes"]).lower())
        self.engine.probe(incident["id"])
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.assertEqual(incident["proposal"]["verdict"], "committed")

    def test_modified_evidence_invalidates_old_proposal(self):
        incident = self.investigate("never_sent")
        path = Path(self.directory.name) / incident["id"] / "evidence" / "settlement_report.json"
        path.write_text('{"records": [], "coverage": {"kind": "lossy", "drop_rate": 1}}')
        with self.assertRaisesRegex(AppError, "Evidence changed"):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(self.engine._simulation_records(incident), [])

    def test_resolution_survives_crash_before_display_state_write(self):
        incident = self.investigate("never_sent")
        with patch.object(self.engine, "_save", side_effect=OSError("simulated write interruption")):
            with self.assertRaises(OSError):
                self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.engine.close()
        self.engine = Engine(self.directory.name, arc_provider=self.arc)
        restored = self.engine.get(incident["id"])
        self.assertEqual(restored["status"], "resolved")
        with self.assertRaises(AppError):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(len(self.engine._simulation_records(restored)), 1)

    def test_one_process_owns_each_data_directory(self):
        with self.assertRaisesRegex(AppError, "already open"):
            Engine(self.directory.name)

    def test_interrupted_creation_remains_discoverable_after_provider_commit(self):
        original = self.engine._simulation_commit

        def commit_then_interrupt(incident, amount):
            original(incident, amount)
            raise OSError("provider committed, application did not acknowledge")

        with patch.object(self.engine, "_simulation_commit", side_effect=commit_then_interrupt):
            with self.assertRaises(OSError):
                self.engine.create("lost_ack")
        self.engine.close()
        self.engine = Engine(self.directory.name, arc_provider=self.arc)
        incidents = self.engine.list_incidents()
        self.assertEqual(len(incidents), 1)
        incident = self.engine.probe(incidents[0]["id"])
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.assertEqual(incident["proposal"]["verdict"], "committed")
        final = self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(final["status"], "resolved")
        self.assertEqual(len(self.engine._simulation_records(final)), 1)

    def test_wallet_dispatch_and_hash_survive_display_write_failure(self):
        first = self.wallet()
        second = self.engine.prepare_wallet(SENDER, RECIPIENT, 20_000)
        with patch.object(self.engine, "_save", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.engine.dispatch_wallet(first["id"])
        with self.assertRaises(AppError):
            self.engine.dispatch_wallet(first["id"])
        with patch.object(self.engine, "_save", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.engine.attach_transaction(first["id"], HASH)
        self.engine.dispatch_wallet(second["id"])
        with self.assertRaisesRegex(AppError, "already assigned"):
            self.engine.attach_transaction(second["id"], HASH)
        self.assertEqual(self.engine.get(first["id"])["wallet"]["transaction_hash"], HASH)

    def test_arc_recovery_only_records_existing_transfer(self):
        incident = self.wallet()
        self.engine.dispatch_wallet(incident["id"])
        self.engine.attach_transaction(incident["id"], HASH)
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.assertEqual(incident["proposal"]["verdict"], "committed")
        self.assertIn(HASH, json.dumps(incident["proposal"]["citations"]))
        with patch.object(self.engine, "_simulation_commit", side_effect=AssertionError("must never send")):
            final = self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(final["outcome"]["action"], "closed_from_evidence")
        self.assertEqual(final["outcome"]["transaction_hash"], HASH)

    def test_arc_missing_or_failed_receipt_cannot_authorize_new_transfer(self):
        for index, status in enumerate(("unknown", "failed"), 1):
            self.arc.status = status
            incident = self.engine.prepare_wallet(SENDER, RECIPIENT, 10_000 * index)
            self.engine.dispatch_wallet(incident["id"])
            incident = self.engine.investigate(incident["id"], "heuristic")
            self.assertEqual(incident["proposal"]["verdict"], "abstain")
            with self.assertRaises(AppError):
                self.engine.resolve(incident["id"], incident["proposal"]["id"])

    def reverted_wallet(self):
        self.engine._arc = FinalizedRevert()
        incident = self.wallet()
        self.engine.dispatch_wallet(incident["id"])
        self.engine.attach_transaction(incident["id"], HASH)
        return self.engine.investigate(incident["id"], "heuristic")

    def test_finalized_revert_closes_without_effect_and_allows_separately_authorized_intent(self):
        incident = self.reverted_wallet()
        self.assertEqual(incident["proposal"]["verdict"], "failed")
        self.assertNotIn("dossier", incident["proposal"])
        self.assertTrue(incident["proposal"]["can_apply"])
        with self.assertRaisesRegex(AppError, "identical test transfer"):
            self.wallet()
        self.engine.revoke(incident["id"])
        with patch.object(self.engine, "_simulation_commit", side_effect=AssertionError("must not send")), \
                patch("recovery_app.engine.apply_dossier", side_effect=AssertionError("not a refund verdict")):
            final = self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(final["status"], "resolved")
        self.assertEqual(final["outcome"]["result"], "failed")
        self.assertEqual(final["outcome"]["transaction_hash"], HASH)
        self.assertTrue(final["outcome"]["gas_may_have_been_spent"])
        receipt = self.engine.receipt(incident["id"])
        closure = [row for row in receipt["journal"] if row["kind"] == "wallet_failed"]
        self.assertEqual(len(closure), 1)
        self.assertEqual(closure[0]["provider_evidence"]["raw"]["receipt"]["gasUsed"], "0x5208")
        self.assertFalse(any(row["kind"] == "adjudicated" for row in receipt["journal"]))
        replacement = self.wallet()
        self.assertNotEqual(replacement["id"], incident["id"])
        self.assertEqual(replacement["status"], "prepared")
        self.assertFalse(replacement["wallet"]["dispatched"])
        self.engine.dispatch_wallet(replacement["id"])
        with self.assertRaisesRegex(AppError, "already assigned"):
            self.engine.attach_transaction(replacement["id"], HASH)
        self.assertFalse(any(method.startswith("eth_send") for method in self.engine._arc.calls))

    def test_failed_closure_survives_interrupted_display_write_and_cannot_repeat(self):
        incident = self.reverted_wallet()
        with patch.object(self.engine, "_save", side_effect=OSError("interrupted after durable closure")):
            with self.assertRaises(OSError):
                self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.engine.close()
        self.engine = Engine(self.directory.name, arc_provider=FinalizedRevert())
        restored = self.engine.get(incident["id"])
        self.assertEqual(restored["status"], "resolved")
        self.assertEqual(restored["outcome"]["result"], "failed")
        self.assertEqual(restored["provider_evidence"]["metadata"]["transaction_hash"], HASH)
        self.assertFalse(restored["proposal"]["can_apply"])
        with self.assertRaises(AppError):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        with self.assertRaises(AppError):
            self.engine.attach_transaction(incident["id"], HASH)
        with self.assertRaises(AppError):
            self.engine.dispatch_wallet(incident["id"])
        self.assertEqual(self.wallet()["status"], "prepared")

    def test_failed_closure_binds_local_evidence_and_journal_revision(self):
        incident = self.reverted_wallet()
        path = Path(self.directory.name) / incident["id"] / "evidence" / "arc_finalized_receipt.json"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(AppError, "Evidence changed"):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.engine._journal(incident).append("operator_note", note="record changed since investigation")
        with self.assertRaisesRegex(AppError, "incident record changed"):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertNotEqual(self.engine.get(incident["id"])["status"], "resolved")

    def test_failed_closure_rechecks_fresh_availability_finality_and_receipt_identity(self):
        incident = self.reverted_wallet()
        for change in ("unavailable", "unfinalized", "different_block"):
            with self.subTest(change=change):
                self.engine._arc = FinalizedRevert()
                incident = self.engine.investigate(incident["id"], "heuristic")
                if change == "unavailable":
                    self.engine._arc.available = False
                elif change == "unfinalized":
                    self.engine._arc.finalized = 100
                else:
                    self.engine._arc.block_hash = "0x" + "ef" * 32
                with self.assertRaisesRegex(AppError, "Arc evidence changed"):
                    self.engine.resolve(incident["id"], incident["proposal"]["id"])
                current = self.engine.get(incident["id"])
                self.assertEqual(current["status"], "needs_evidence")
                self.assertIsNone(current["proposal"])
                with self.assertRaisesRegex(AppError, "identical test transfer"):
                    self.wallet()

    def test_revert_without_finality_remains_unknown_and_later_head_does_not_invalidate_receipt(self):
        incident = self.reverted_wallet()
        self.engine._arc.finalized = 100
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.assertEqual(incident["proposal"]["verdict"], "abstain")
        with self.assertRaises(AppError):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.engine._arc.finalized = 102
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.engine._arc.finalized = 105
        final = self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(final["outcome"]["result"], "failed")
        self.assertEqual(final["provider_evidence"]["metadata"]["finalized_block_number"], 105)

    def test_committed_arc_closure_also_requires_a_current_verified_receipt(self):
        incident = self.wallet()
        self.engine.dispatch_wallet(incident["id"])
        self.engine.attach_transaction(incident["id"], HASH)
        incident = self.engine.investigate(incident["id"], "heuristic")
        self.arc.status = "unknown"
        with self.assertRaisesRegex(AppError, "Arc evidence changed"):
            self.engine.resolve(incident["id"], incident["proposal"]["id"])
        self.assertEqual(self.engine.get(incident["id"])["status"], "needs_evidence")

    def test_identical_pending_wallet_intents_cannot_compete_for_one_receipt(self):
        self.wallet()
        with self.assertRaisesRegex(AppError, "identical test transfer"):
            self.wallet()

    def test_close_waits_for_active_operation_and_rejects_future_work(self):
        entered = threading.Event()
        release = threading.Event()
        closed = threading.Event()
        failures = []
        original = self.arc.head

        def paused_head():
            entered.set()
            self.assertTrue(release.wait(5))
            return original()

        def prepare():
            try:
                self.wallet()
            except Exception as exc:
                failures.append(exc)

        def close():
            self.engine.close()
            closed.set()

        with patch.object(self.arc, "head", side_effect=paused_head):
            worker = threading.Thread(target=prepare)
            worker.start()
            self.assertTrue(entered.wait(5))
            closer = threading.Thread(target=close)
            closer.start()
            self.assertFalse(closed.wait(0.05))
            with self.assertRaises(AppError):
                Engine(self.directory.name)
            release.set()
            worker.join(5)
            closer.join(5)
        self.assertFalse(failures)
        self.assertTrue(closed.is_set())
        with self.assertRaisesRegex(AppError, "closed"):
            self.engine.create("lost_ack")
        self.engine = Engine(self.directory.name, arc_provider=self.arc)
        self.assertEqual(len(self.engine.list_incidents()), 1)

    def test_wallet_amount_and_addresses_are_bounded(self):
        for value in (True, 1, 9999, 1_000_001, -1, 10_001, "10000"):
            with self.assertRaises(AppError):
                self.engine.prepare_wallet(SENDER, RECIPIENT, value)
        with self.assertRaises(AppError):
            self.engine.prepare_wallet(SENDER, SENDER, 10_000)

    def test_no_model_credentials_are_returned_or_required(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            config = self.engine.config()
            self.assertFalse(config["agents"][1]["available"])
            incident = self.engine.create("lost_ack")
            with self.assertRaises(AppError):
                self.engine.investigate(incident["id"], "openai")
            self.assertIsNone(self.engine.get(incident["id"])["proposal"])

    def test_http_disallows_foreign_origins_and_undeclared_fields(self):
        server = make_server(self.engine, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            request = urllib.request.Request(base + "/api/incidents", data=b'{"scenario":"lost_ack"}',
                                             headers={"Content-Type": "application/json", "Origin": "https://elsewhere.example"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
            request = urllib.request.Request(base + "/api/incidents", data=b'{"scenario":"lost_ack","amount":1}',
                                             headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 400)
            request = urllib.request.Request(base + "/api/incidents", data=b'{"scenario":"lost_ack"}',
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                incident = json.load(response)
            self.assertEqual(incident["intent"]["amount_cents"], 5000)
            with urllib.request.urlopen(base + "/api/incidents/" + incident["id"] + "/receipt") as response:
                self.assertIn("attachment", response.headers["Content-Disposition"])
                self.assertGreater(len(json.load(response)["journal"]), 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
