"""Recovery must reconcile original evidence without creating payment authority."""

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

from purchase_simulator.engine import DemoError, Engine
from purchase_simulator.mission_control import MissionEngine
from purchase_simulator.server import make_server


class MissionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = MissionEngine(self.directory.name)

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def run_to(self, status="payout_unknown", *, outcome="payout_reply_lost"):
        state = self.engine.analyze("Pay $20 to Acme", demo_outcome=outcome)
        state = self.engine.authorize(state["id"], state["revision"])
        while state["status"] != status:
            self.assertTrue(state["can_advance"], state)
            state = self.engine.advance(state["id"], state["revision"])
        return state

    def execute(self, statement, values=()):
        with closing(sqlite3.connect(self.engine.path)) as db, db:
            db.execute(statement, values)

    def investigate(self, state):
        return self.engine.investigate(state["id"], state["revision"])

    def test_lost_reply_investigation_is_read_only_then_accounts_original_once(self):
        state = self.run_to()
        self.assertFalse(state["terminal"])
        self.assertFalse(state["can_advance"])
        self.assertTrue(state["can_investigate"])
        self.assertEqual(state["money"]["provider_in_transit_usdc_units"], 20_000_000)
        self.assertEqual(state["money"]["payee_received_usd_cents"], 0)
        finding = self.investigate(state)
        self.assertEqual(self.engine.get(state["id"]), state)
        self.assertEqual(finding["schema_version"], "belay.payment.investigation.v1")
        self.assertEqual(finding["verdict"], "paid")
        self.assertEqual(finding["intent_digest"], state["recovery_intent_digest"])
        self.assertNotIn("order_id", finding["intent"])
        self.assertEqual(finding["intent"]["source_usdc_units"], 20_000_000)
        self.assertEqual(finding["intent"]["net_usd_cents"], 2_000)
        self.assertTrue(finding["citations"])
        self.assertEqual(finding["mode"], "deterministic")
        paid = self.engine.reconcile(state["id"], state["revision"], finding["evidence_digest"])
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(paid["money"]["provider_in_transit_usdc_units"], 0)
        self.assertEqual(paid["money"]["payee_received_usd_cents"], 2_000)
        with self.assertRaises(DemoError):
            self.engine.reconcile(paid["id"], paid["revision"], finding["evidence_digest"])
        final = self.engine.advance(paid["id"], paid["revision"])
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["provider_payment"]["attempt_count"], 1)
        self.assertEqual(len(final["ledger"]), 3)
        self.assertEqual(final["receipt"]["domain_outcome"]["status"], "not_verified")

    def test_restart_and_expired_grant_do_not_release_or_redispatch(self):
        state = self.run_to()
        self.engine.close()
        self.engine = MissionEngine(self.directory.name)
        self.assertEqual(self.engine.get(state["id"]), state)
        with patch("purchase_simulator.mission_control.time.time", return_value=state["grant"]["expires_at"] + 500):
            with self.assertRaises(DemoError):
                self.engine.advance(state["id"], state["revision"])
            finding = self.investigate(state)
            paid = self.engine.reconcile(state["id"], state["revision"], finding["evidence_digest"])
        self.assertEqual(paid["money"]["customer_available_usdc_units"], state["money"]["customer_available_usdc_units"])
        self.assertEqual(paid["provider_payment"]["attempt_count"], 1)

    def test_pending_provider_and_missing_evidence_cannot_be_reconciled(self):
        state = self.run_to("dispatched")
        finding = self.investigate(state)
        self.assertEqual(finding["verdict"], "unknown")
        self.assertEqual(finding["operation_id"], state["operation_id"])
        self.assertEqual(finding["intent_digest"], state["recovery_intent_digest"])
        self.execute("DELETE FROM mission_payments WHERE operation_id=?", (state["operation_id"],))
        finding = self.investigate(state)
        self.assertEqual(finding["verdict"], "unknown")
        self.assertFalse(finding["can_reconcile"])
        reviewed = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(reviewed["status"], "review_required")
        self.assertTrue(reviewed["can_investigate"])
        self.assertFalse(reviewed["terminal"])
        self.assertEqual(reviewed["money"], state["money"])

    def test_each_saved_provider_identity_and_currency_field_is_checked(self):
        fields = {
            "mission_id": "another_mission", "payee_id": "wrong_beneficiary",
            "amount_usd_cents": 3_000, "source_usdc_units": 20_000_001,
            "source_asset": "ETH", "destination_asset": "USDC",
            "intent_json": "{}", "grant_json": "{}", "provider_reference": "",
            "attempt_count": 2,
        }
        for column, wrong in fields.items():
            with self.subTest(column=column):
                state = self.run_to()
                self.execute(f"UPDATE mission_payments SET {column}=? WHERE operation_id=?", (wrong, state["operation_id"]))
                finding = self.investigate(state)
                self.assertFalse(finding["can_reconcile"])
                self.assertNotEqual(finding["verdict"], "paid")
                with self.assertRaises(DemoError):
                    self.engine.reconcile(state["id"], state["revision"], finding["evidence_digest"])
                current = self.engine.get(state["id"])
                self.assertEqual(current["money"], state["money"])
                self.assertEqual(current["ledger"], state["ledger"])

    def test_old_payment_without_captured_intent_stays_unresolved(self):
        state = self.run_to("dispatched", outcome="success")
        self.execute("UPDATE mission_payments SET intent_json=NULL,grant_json=NULL WHERE operation_id=?", (state["operation_id"],))
        finding = self.investigate(state)
        self.assertEqual(finding["verdict"], "unknown")
        self.assertEqual(finding["operation_id"], state["operation_id"])
        self.assertEqual(finding["intent_digest"], state["recovery_intent_digest"])
        reviewed = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(reviewed["status"], "review_required")
        self.assertEqual(reviewed["money"], state["money"])
        self.assertTrue(reviewed["can_investigate"])

    def test_provider_changed_after_investigation_rejects_previous_digest(self):
        state = self.run_to()
        finding = self.investigate(state)
        self.execute("UPDATE mission_payments SET provider_reference='changed_reference' WHERE operation_id=?", (state["operation_id"],))
        with self.assertRaises(DemoError) as conflict:
            self.engine.reconcile(state["id"], state["revision"], finding["evidence_digest"])
        self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(self.engine.get(state["id"])["money"], state["money"])
        fresh = self.investigate(state)
        self.assertNotEqual(fresh["evidence_digest"], finding["evidence_digest"])
        self.assertEqual(self.engine.reconcile(state["id"], state["revision"], fresh["evidence_digest"])["status"], "paid")

    def test_two_engines_cannot_reconcile_the_same_revision_twice(self):
        state = self.run_to()
        finding = self.investigate(state)
        other = MissionEngine(self.directory.name)
        barrier = threading.Barrier(2)

        def reconcile(engine):
            barrier.wait(timeout=5)
            try:
                return engine.reconcile(state["id"], state["revision"], finding["evidence_digest"])
            except DemoError as exc:
                return exc.status

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(reconcile, (self.engine, other)))
        finally:
            other.close()
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn(409, results)
        current = self.engine.get(state["id"])
        self.assertEqual(len(current["ledger"]), 3)
        self.assertEqual(current["money"]["payee_received_usd_cents"], 2_000)

    def test_failed_accounting_transaction_keeps_evidence_recoverable(self):
        state = self.run_to()
        finding = self.investigate(state)
        with patch.object(self.engine, "_save", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.engine.reconcile(state["id"], state["revision"], finding["evidence_digest"])
        self.assertEqual(self.engine.get(state["id"]), state)
        paid = self.engine.reconcile(state["id"], state["revision"], finding["evidence_digest"])
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(paid["provider_payment"]["attempt_count"], 1)

    def test_corrupt_signed_authority_cannot_become_a_recovery_instruction(self):
        state = self.run_to()
        with closing(sqlite3.connect(self.engine.path)) as db, db:
            raw = json.loads(db.execute("SELECT state_json FROM missions WHERE id=?", (state["id"],)).fetchone()[0])
            raw["grant"]["payee_id"] = "wrong_payee"
            db.execute("UPDATE missions SET state_json=? WHERE id=?", (json.dumps(raw), state["id"]))
        finding = self.investigate(state)
        self.assertEqual(finding["verdict"], "unknown")
        self.assertFalse(finding["can_reconcile"])
        self.assertIsNone(self.engine.get(state["id"])["recovery_intent_digest"])

    def test_revision_and_demo_outcome_are_validated(self):
        for outcome in (None, True, {}, "pay_again"):
            with self.assertRaises(DemoError):
                self.engine.analyze("Pay $20 to Acme", demo_outcome=outcome)
        state = self.run_to()
        for revision in (True, -1, "6", state["revision"] - 1):
            with self.assertRaises(DemoError):
                self.engine.investigate(state["id"], revision)


class MissionRecoveryHTTPTests(unittest.TestCase):
    def test_http_flow_rejects_forged_findings_and_cross_origin_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(directory)
            server = make_server(engine, port=0)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()

            def post(path, body, *, origin=None):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    connection.request("POST", path, json.dumps(body), headers={
                        "Content-Type": "application/json",
                        "Origin": origin or f"http://127.0.0.1:{server.server_port}",
                    })
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()

            try:
                code, state = post("/api/missions/analyze", {"request": "Pay $20 to Acme", "demo_outcome": "payout_reply_lost"})
                self.assertEqual(code, 201)
                prefix = f"/api/missions/{state['id']}"
                code, state = post(prefix + "/authorize", {"expected_revision": state["revision"]})
                while state["can_advance"]:
                    code, state = post(prefix + "/advance", {"expected_revision": state["revision"]})
                    self.assertEqual(code, 200)
                self.assertEqual(state["status"], "payout_unknown")
                revision = state["revision"]
                code, finding = post(prefix + "/investigate", {"expected_revision": revision})
                self.assertEqual(code, 200)
                self.assertEqual(finding["verdict"], "paid")
                self.assertEqual(post(prefix + "/investigate", {"expected_revision": revision, "verdict": "paid"})[0], 400)
                self.assertEqual(post(prefix + "/reconcile", {"expected_revision": revision, "evidence_digest": finding["evidence_digest"], "can_reconcile": True})[0], 400)
                self.assertEqual(post(prefix + "/reconcile", {"expected_revision": revision, "evidence_digest": finding["evidence_digest"]}, origin="https://attacker.invalid")[0], 403)
                self.assertEqual(server.mission_engine.get(state["id"]), state)
                code, paid = post(prefix + "/reconcile", {"expected_revision": revision, "evidence_digest": finding["evidence_digest"]})
                self.assertEqual(code, 200)
                self.assertEqual(paid["status"], "paid")
                self.assertEqual(post(prefix + "/reconcile", {"expected_revision": revision, "evidence_digest": finding["evidence_digest"]})[0], 409)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                engine.close()
