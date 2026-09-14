"""The purchase-to-Recovery-Desk bridge only inspects exact typed evidence."""

import copy
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from purchase_simulator.engine import DemoError, Engine  # noqa: E402
from purchase_simulator.recovery import intent_from_state, investigate  # noqa: E402
from purchase_simulator.server import make_server  # noqa: E402
from recovery_app.purchase import investigate as inspect_evidence  # noqa: E402


class PurchaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = Engine(self.directory.name)
        self.state = self.engine.create("payout_reply_lost", 30_000)
        while self.state["step"] < 8:
            self.state = self.engine.advance(self.state["id"], self.state["revision"])
        self.provider = self.engine.provider.lookup(self.state["operation_id"])

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def test_investigation_is_read_only_and_preserves_separate_currencies(self):
        before = self.engine.get(self.state["id"])
        with patch.object(self.engine.provider, "submit", side_effect=AssertionError("no send")), \
                patch.object(self.engine.provider, "complete", side_effect=AssertionError("no payout")), \
                patch.object(self.engine.provider, "convert", side_effect=AssertionError("no conversion")):
            finding = self.engine.investigate(self.state["id"], self.state["revision"])
        self.assertEqual(finding["verdict"], "paid")
        self.assertTrue(finding["can_reconcile"])
        self.assertEqual(finding["intent"]["source_usdc_units"], 200_000_000)
        self.assertEqual(finding["intent"]["net_usd_cents"], 20_000)
        self.assertNotIn("amount_cents", finding["intent"])
        self.assertEqual(finding["citations"], [finding["observations"][0]["digest"]])
        self.assertEqual(self.engine.get(self.state["id"]), before)
        self.assertEqual(self.engine.provider.lookup(self.state["operation_id"]), self.provider)

    def test_unknown_payout_routes_through_recovery_desk_before_reconciliation(self):
        with patch.object(self.engine.provider, "submit", side_effect=AssertionError("no repeat")), \
                patch.object(self.engine.provider, "complete", side_effect=AssertionError("no repeat")):
            after = self.engine.advance(self.state["id"], self.state["revision"])
        self.assertEqual(after["stage"], "payout_reconciled")
        finding = after["events"][-1]["response"]["recovery_finding"]
        self.assertEqual(finding["schema_version"], "belay.purchase.investigation.v1")
        self.assertEqual(finding["revision"], self.state["revision"])
        self.assertEqual(after["settlement"]["provider_payout_count"], 1)
        self.assertEqual(after["settlement"]["merchant_received_usd_cents"], 20_000)
        with self.assertRaises(DemoError):
            self.engine.investigate(self.state["id"], self.state["revision"])

    def test_disagreement_or_ambiguous_provider_cannot_be_paid(self):
        intent = intent_from_state(self.state)
        for field, value in (
            ("operation_id", "another_operation"), ("beneficiary_id", "another_merchant"),
            ("source_usdc_units", 20_000), ("net_usd_cents", 200_000_000),
            ("source_usdc_units", True), ("intent_json", "{}"),
            ("funding_state", "received"), ("conversion_state", "pending"),
        ):
            record = {**self.provider, field: value}
            with self.subTest(field=field, value=value):
                finding = inspect_evidence(intent, record)
                self.assertEqual(finding["verdict"], "conflict")
                self.assertFalse(finding["can_reconcile"])
        for record in (None, {**self.provider, "payout_state": "pending"},
                       {**self.provider, "payout_state": "returned"}):
            self.assertFalse(inspect_evidence(intent, record)["can_reconcile"])

    def test_provider_failure_and_malformed_evidence_stay_unknown(self):
        def unavailable(_operation):
            raise OSError("private diagnostic must not be exposed")

        finding = investigate(self.state, unavailable)
        self.assertEqual(finding["verdict"], "unknown")
        self.assertNotIn("private diagnostic", json.dumps(finding))
        intent = intent_from_state(self.state)
        for record in ([], {"oversized": "x" * 20_000}, {"bad": float("nan")}):
            self.assertFalse(inspect_evidence(intent, record)["can_reconcile"])

    def test_modified_original_intent_never_calls_provider(self):
        bad = copy.deepcopy(self.state)
        bad["fx_quote"]["source_asset"] = "USD"
        finding = investigate(bad, lambda _op: self.fail("do not query using invalid intent"))
        self.assertFalse(finding["can_reconcile"])
        self.assertEqual(finding["observations"], [])

    def test_mismatch_and_missing_evidence_do_not_mutate_accounts(self):
        before = self.engine.get(self.state["id"])
        for record in (None, {**self.provider, "net_usd_cents": 1}):
            with patch.object(self.engine.provider, "lookup", return_value=record):
                with self.assertRaises(DemoError):
                    self.engine.advance(self.state["id"], self.state["revision"])
            self.assertEqual(self.engine.get(self.state["id"]), before)

    def test_http_requires_exact_revision_and_rejects_supplied_findings(self):
        server = make_server(self.engine, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            path = "/api/runs/" + self.state["id"] + "/investigate"
            for payload, expected in (({"expected_revision": self.state["revision"]}, 200),
                                      ({"expected_revision": 0}, 409),
                                      ({"expected_revision": self.state["revision"], "can_reconcile": True}, 400)):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("POST", path, json.dumps(payload), {"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                response.read()
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
