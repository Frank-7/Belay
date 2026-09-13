"""Portable end-to-end checks against a real loopback HTTP mock provider."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from prototype.engine import DemoError, Engine, connect
from prototype.server import make_server


class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(self.tmp.name)

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def test_lost_ack_recovers_exactly_one_original_refund(self):
        case = self.engine.create("lost_ack", "belay")
        self.assertEqual(case["status"], "pending")
        self.assertEqual(case["total_refunded_cents"], 5000)
        with connect(self.engine.path) as db:
            self.assertIsNone(db.execute("SELECT receipt_json FROM cases WHERE id=?", (case["id"],)).fetchone()[0])
        recovered = self.engine.recover(case["id"])
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(len(recovered["refunds"]), 1)
        self.assertEqual(recovered["refunds"][0]["reference"], case["anchor"])
        self.assertEqual(recovered["amount_cents"], 5000)
        self.assertEqual(recovered["refunds"][0]["id"], case["refunds"][0]["id"])

    def test_naive_retry_creates_second_refund_for_different_amount(self):
        first = self.engine.create("lost_ack", "naive")
        result = self.engine.recover(first["id"])
        self.assertEqual(result["total_refunded_cents"], 8000)
        self.assertEqual([r["amount_cents"] for r in result["refunds"]], [5000, 3000])
        self.assertNotEqual(result["refunds"][0]["reference"], result["refunds"][1]["reference"])
        self.assertEqual(result["order_amount_cents"], 10000)
        self.assertEqual(result["proposed_retry_cents"], 3000)

    def test_opaque_halts_without_using_ledger_as_recovery_oracle(self):
        case = self.engine.create("opaque", "belay")
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.engine.provider.lookup(case["id"], case["anchor"])
        self.assertEqual(denied.exception.code, 405)
        denied.exception.close()
        original_lookup = self.engine.provider.lookup
        def forbidden(*args):
            self.fail("Opaque recovery must not invoke provider lookup")
        self.engine.provider.lookup = forbidden
        try:
            result = self.engine.recover(case["id"])
        finally:
            self.engine.provider.lookup = original_lookup
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["total_refunded_cents"], 5000)
        with connect(self.engine.path) as db:
            self.assertIsNone(db.execute("SELECT receipt_json FROM cases WHERE id=?", (case["id"],)).fetchone()[0])

    def test_revoked_permission_prevents_new_effect(self):
        case = self.engine.create("revoked", "belay")
        self.assertFalse(case["authorized"])
        self.assertEqual(case["total_refunded_cents"], 0)
        result = self.engine.recover(case["id"])
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["refunds"], [])

    def test_readonly_reconciliation_can_finish_after_permission_revoked(self):
        case = self.engine.create("lost_ack", "belay")
        with connect(self.engine.path) as db:
            db.execute("UPDATE cases SET authorized=0 WHERE id=?", (case["id"],))
        result = self.engine.recover(case["id"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["authorized"])
        self.assertEqual(result["total_refunded_cents"], 5000)

    def test_before_send_uses_original_intent_and_anchor(self):
        case = self.engine.create("before_send", "belay")
        self.assertEqual(case["refunds"], [])
        result = self.engine.recover(case["id"])
        self.assertEqual(result["total_refunded_cents"], 5000)
        self.assertEqual(result["refunds"][0]["reference"], case["anchor"])

    def test_naive_changed_decision_before_send_reports_underfulfillment(self):
        case = self.engine.create("before_send", "naive")
        result = self.engine.recover(case["id"])
        self.assertEqual(result["total_refunded_cents"], 3000)
        self.assertEqual(result["amount_cents"], 5000)
        self.assertEqual(result["outcome"]["title"], "Refund differs from original intent")
        self.assertIn("$20.00 less", result["outcome"]["detail"])

    def test_repeated_and_concurrent_recovery_does_not_duplicate(self):
        case = self.engine.create("before_send", "belay")
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(self.engine.recover, [case["id"]] * 12))
        for result in results:
            self.assertEqual(result["total_refunded_cents"], 5000)
            self.assertEqual(len(result["refunds"]), 1)
        self.assertEqual(self.engine.recover(case["id"])["total_refunded_cents"], 5000)

    def test_app_restart_preserves_intent_provider_evidence_and_recovery(self):
        case = self.engine.create("lost_ack", "belay")
        self.engine.close()
        self.engine = Engine(self.tmp.name)
        persisted = self.engine.get(case["id"])
        self.assertEqual(persisted["anchor"], case["anchor"])
        self.assertEqual(persisted["status"], "pending")
        result = self.engine.recover(case["id"])
        self.assertEqual(result["total_refunded_cents"], 5000)
        self.assertEqual(result["status"], "completed")

    def test_clean_records_receipt(self):
        result = self.engine.create("clean", "belay")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["total_refunded_cents"], 5000)

    def test_anchor_without_durable_intent_can_resume_before_any_submission(self):
        case = self.engine.create("before_send", "belay")
        # Reconstruct the durable boundary immediately after anchor allocation.
        with connect(self.engine.path) as db:
            db.execute("UPDATE cases SET amount_cents=NULL,request_json=NULL WHERE id=?", (case["id"],))
        result = self.engine.recover(case["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["amount_cents"], 5000)
        self.assertEqual(result["request"]["body"]["reference"], case["anchor"])
        self.assertEqual(result["total_refunded_cents"], 5000)

    def test_existing_idempotency_also_prevents_duplicate_refund(self):
        case = self.engine.create("lost_ack", "idempotent")
        result = self.engine.recover(case["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["total_refunded_cents"], 5000)
        self.assertEqual(result["refunds"][0]["id"], case["refunds"][0]["id"])
        self.assertEqual(result["request"]["body"]["reference"], case["anchor"])

    def test_idempotency_requires_provider_support_and_live_permission(self):
        opaque = self.engine.create("opaque", "idempotent")
        self.assertEqual(self.engine.recover(opaque["id"])["status"], "blocked")
        revoked = self.engine.create("revoked", "idempotent")
        result = self.engine.recover(revoked["id"])
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["refunds"], [])

    def test_invalid_options_and_unknown_case(self):
        for scenario, mode in [("bad", "belay"), ("clean", "bad"), ([], "belay"), ("clean", None)]:
            with self.assertRaises(DemoError) as caught:
                self.engine.create(scenario, mode)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(DemoError) as caught:
            self.engine.get("unknown")
        self.assertEqual(caught.exception.status, 404)

    def test_http_api_json_errors_and_cross_origin_rejection(self):
        server = make_server(self.engine, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_port)
        def send(path, body, extra=None):
            headers = {"Content-Type": "application/json"}
            headers.update(extra or {})
            request = urllib.request.Request(base + path, data=body, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                return exc.code, json.load(exc)
        try:
            status, payload = send("/api/cases", b'{"scenario":"clean","mode":"belay"}')
            self.assertEqual(status, 201)
            self.assertEqual(payload["status"], "completed")
            for body in [b"{", b"[]", b'{"scenario":"bad","mode":"belay"}']:
                status, payload = send("/api/cases", body)
                self.assertEqual(status, 400)
                self.assertIn("error", payload)
            self.assertEqual(send("/api/cases", b"{}", {"Origin": "https://evil.example"})[0], 403)
            self.assertEqual(send("/api/cases", b"{}", {"Host": "evil.example"})[0], 403)
            self.assertEqual(send("/api/cases", b"{}", {"Content-Type": "text/plain"})[0], 415)
            self.assertEqual(send("/api/cases/" + "0" * 32 + "/recover", b"{}")[0], 404)
            with urllib.request.urlopen(base + "/api/cases", timeout=5) as response:
                self.assertEqual(len(json.load(response)["cases"]), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
