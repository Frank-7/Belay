"""Portable purchase simulator regressions; all money and credentials are fictitious.

The HTTP checks use a real loopback server. Payment outcomes use the local
provider simulator, with no remote model, payment network, or actual bank.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from purchase_simulator.engine import DemoError, Engine  # noqa: E402
from purchase_simulator.server import make_server  # noqa: E402


class PurchaseEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-purchase-test-")
        self.engine = Engine(self.directory.name)

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def create(self, scenario="success", budget=30000):
        return self.engine.create(scenario, budget, quantity=2)

    def to_step(self, state, step):
        for _ in range(20):
            if state["step"] >= step or state["terminal"]:
                break
            state = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(state["step"], step)
        return state

    def finish(self, state):
        for _ in range(20):
            if state["terminal"]:
                return state
            state = self.engine.advance(state["id"], state["revision"])
        self.fail("Purchase failed to reach a terminal state within 20 transitions")

    def restart(self):
        self.engine.close()
        self.engine = Engine(self.directory.name)

    def assert_no_spend(self, state):
        self.assertEqual(state["provider_charge_count"], 0)
        self.assertEqual(state["budget"]["spent_cents"], 0)

    def test_success_creates_one_charge_and_persists_completed_purchase(self):
        state = self.finish(self.create())
        self.assertEqual(state["provider_charge_count"], 1)
        self.assertEqual(state["budget"]["spent_cents"], 28000)
        self.assertEqual(state["budget"]["reserved_cents"], 0)
        self.assertIsNotNone(state["artifacts"]["payment_id"])
        self.assertIsNotNone(state["artifacts"]["order_id"])
        self.assertEqual(state["artifacts"]["intent"]["operation_id"], state["operation_id"])
        self.restart()
        restored = self.engine.get(state["id"])
        for key in ("revision", "step", "terminal", "operation_id", "budget", "artifacts"):
            self.assertEqual(restored[key], state[key], key)
        self.assertEqual(restored["provider_charge_count"], 1)

    def test_lost_reply_holds_reservation_and_recovers_same_operation_after_restart(self):
        unknown = self.to_step(self.create("lost_reply"), 10)
        self.assertEqual(unknown["payment_status"], "capture_unknown")
        self.assertEqual(unknown["order_status"], "unknown")
        self.assertEqual(unknown["provider_charge_count"], 1)
        self.assertEqual(unknown["budget"]["reserved_cents"], 28000)
        self.assertEqual(unknown["budget"]["spent_cents"], 0)
        operation = unknown["operation_id"]
        self.restart()
        restored = self.engine.get(unknown["id"])
        self.assertEqual(restored["budget"], unknown["budget"])
        self.assertEqual(restored["payment_status"], "capture_unknown")
        self.assertEqual(restored["provider_charge_count"], 1)
        recovered = self.engine.advance(restored["id"], restored["revision"])
        self.assertEqual(recovered["operation_id"], operation)
        self.assertEqual(recovered["provider_charge_count"], 1)
        self.assertEqual(recovered["budget"]["reserved_cents"], 0)
        self.assertEqual(recovered["budget"]["spent_cents"], 28000)
        self.assertNotEqual(recovered["payment_status"], "capture_unknown")
        completed = self.finish(recovered)
        self.assertEqual(completed["provider_charge_count"], 1)
        self.assertEqual(completed["operation_id"], operation)

    def test_price_increase_above_cap_stops_before_token_or_charge(self):
        state = self.finish(self.create("price_change"))
        self.assertEqual(state["step"], 3)
        self.assert_no_spend(state)
        self.assertEqual(state["budget"]["reserved_cents"], 0)
        self.assertEqual(state["payment_status"], "not_started")
        self.assertEqual(state["order_status"], "not_submitted")
        self.assertIsNone(state["artifacts"]["payment_token"])
        self.assertIsNone(state["artifacts"]["payment_id"])

    def test_bank_challenge_requires_explicit_current_verification(self):
        paused = self.to_step(self.create("bank_verification"), 9)
        self.assertTrue(paused["needs_verification"])
        self.assertFalse(paused["can_advance"])
        self.assert_no_spend(paused)
        self.assertEqual(paused["budget"]["reserved_cents"], 28000)
        with self.assertRaises(DemoError):
            self.engine.advance(paused["id"], paused["revision"])
        with self.assertRaises(DemoError) as stale:
            self.engine.verify(paused["id"], paused["revision"] - 1)
        self.assertEqual(stale.exception.status, 409)
        unchanged = self.engine.get(paused["id"])
        self.assertEqual(unchanged["revision"], paused["revision"])
        self.assertTrue(unchanged["needs_verification"])
        self.assert_no_spend(unchanged)
        verified = self.engine.verify(paused["id"], paused["revision"])
        self.assertEqual(verified["step"], 9)
        self.assertEqual(verified["revision"], paused["revision"] + 1)
        self.assertFalse(verified["needs_verification"])
        self.assert_no_spend(verified)
        completed = self.finish(verified)
        self.assertEqual(completed["provider_charge_count"], 1)

    def test_verification_cannot_skip_checkout_or_authorization_steps(self):
        initial = self.create("bank_verification")
        with self.assertRaises(DemoError) as stopped:
            self.engine.verify(initial["id"], initial["revision"])
        self.assertEqual(stopped.exception.status, 409)
        state = self.engine.get(initial["id"])
        self.assertEqual(state["step"], 0)
        self.assertEqual(state["revision"], initial["revision"])
        self.assert_no_spend(state)

    def test_repeated_capture_revision_is_rejected_without_another_charge(self):
        ready = self.to_step(self.create(), 9)
        captured = self.engine.advance(ready["id"], ready["revision"])
        with self.assertRaises(DemoError) as stale:
            self.engine.advance(ready["id"], ready["revision"])
        self.assertEqual(stale.exception.status, 409)
        current = self.engine.get(ready["id"])
        self.assertEqual(current["revision"], captured["revision"])
        self.assertEqual(current["provider_charge_count"], 1)
        self.assertEqual(current["budget"], captured["budget"])

    def test_concurrent_advance_with_same_revision_captures_once(self):
        ready = self.to_step(self.create(), 9)
        start = threading.Barrier(2)

        def advance():
            start.wait(timeout=5)
            try:
                return self.engine.advance(ready["id"], ready["revision"])
            except DemoError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: advance(), range(2)))
        accepted = [value for value in outcomes if isinstance(value, dict)]
        rejected = [value for value in outcomes if isinstance(value, DemoError)]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].status, 409)
        self.assertEqual(self.engine.get(ready["id"])["provider_charge_count"], 1)

    def test_declined_authorization_releases_reservation_without_capture(self):
        state = self.finish(self.create("declined"))
        self.assert_no_spend(state)
        self.assertEqual(state["budget"]["reserved_cents"], 0)
        self.assertEqual(state["payment_status"], "declined")
        self.assertEqual(state["order_status"], "not_confirmed")
        self.assertEqual(state["tickets"], [])

    def test_expiry_before_signing_token_or_submission_stops_and_releases_budget(self):
        for gate in (3, 5, 6):
            with self.subTest(gate=gate):
                ready = self.to_step(self.create(), gate - 1)
                self.assertEqual(ready["budget"]["reserved_cents"], 0 if gate == 3 else 28000)
                with (
                    patch("purchase_simulator.engine.time.time", return_value=ready["grant"]["expires_at"] + 1),
                    patch.object(self.engine, "_provider_submit", wraps=self.engine._provider_submit) as submit,
                    patch.object(self.engine, "_provider_capture", wraps=self.engine._provider_capture) as capture,
                ):
                    expired = self.engine.advance(ready["id"], ready["revision"])
                submit.assert_not_called()
                capture.assert_not_called()
                self.assertTrue(expired["terminal"])
                self.assertFalse(expired["can_advance"])
                self.assertEqual(expired["stage"], "expired")
                self.assertEqual(expired["step"], gate)
                self.assert_no_spend(expired)
                self.assertEqual(expired["budget"]["reserved_cents"], 0)
                self.assertEqual(expired["budget"]["available_cents"], 30000)
                self.assertEqual(expired["grant"], ready["grant"])
                self.assertIsNone(self.engine._provider_lookup(ready["operation_id"]))
                if gate == 3:
                    self.assertIsNone(expired["artifacts"]["signature"])
                if gate in (3, 5):
                    self.assertIsNone(expired["artifacts"]["payment_token"])

    def test_expired_bank_verification_cannot_authorize_or_release_pending_reservation(self):
        paused = self.to_step(self.create("bank_verification"), 9)
        with (
            patch("purchase_simulator.engine.time.time", return_value=paused["grant"]["expires_at"] + 1),
            patch.object(self.engine, "_provider_authorize", wraps=self.engine._provider_authorize) as authorize,
        ):
            with self.assertRaises(DemoError) as stopped:
                self.engine.verify(paused["id"], paused["revision"])
        authorize.assert_not_called()
        self.assertEqual(stopped.exception.status, 409)
        current = self.engine.get(paused["id"])
        self.assertEqual(current["revision"], paused["revision"])
        self.assertEqual(current["payment_status"], "requires_verification")
        self.assertTrue(current["needs_verification"])
        self.assert_no_spend(current)
        self.assertEqual(current["budget"]["reserved_cents"], 28000)
        self.assertEqual(current["budget"], paused["budget"])

    def test_expired_grant_allows_read_only_reconciliation_of_existing_payment(self):
        unknown = self.to_step(self.create("lost_reply"), 10)
        with (
            patch("purchase_simulator.engine.time.time", return_value=unknown["grant"]["expires_at"] + 1),
            patch.object(self.engine, "_provider_submit", wraps=self.engine._provider_submit) as submit,
            patch.object(self.engine, "_provider_authorize", wraps=self.engine._provider_authorize) as authorize,
            patch.object(self.engine, "_provider_capture", wraps=self.engine._provider_capture) as capture,
        ):
            recovered = self.engine.advance(unknown["id"], unknown["revision"])
        submit.assert_not_called()
        authorize.assert_not_called()
        capture.assert_not_called()
        self.assertEqual(recovered["stage"], "reconciled")
        self.assertEqual(recovered["payment_status"], "captured")
        self.assertEqual(recovered["operation_id"], unknown["operation_id"])
        self.assertEqual(recovered["provider_charge_count"], 1)
        self.assertEqual(recovered["budget"]["reserved_cents"], 0)
        self.assertEqual(recovered["budget"]["spent_cents"], 28000)
        self.assertEqual(recovered["events"][-1]["method"], "GET")
        self.assertFalse(recovered["events"][-1]["request"]["creates_payment"])

    def test_checkout_and_payment_bind_exact_saved_intent_and_preserve_original_grant(self):
        initial = self.create()
        original_grant = initial["grant"]
        self.assertIs(type(original_grant["expires_at"]), int)
        self.assertEqual(original_grant["expires_at"] - original_grant["issued_at"], 1800)
        payment = self.to_step(initial, 4)
        artifacts = payment["artifacts"]
        intent = artifacts["intent"]
        canonical = json.dumps(intent, sort_keys=True, separators=(",", ":"), allow_nan=False)
        expected_binding = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(artifacts["checkout_binding"], expected_binding)
        checkout = artifacts["checkout_authorization"]
        mandate = artifacts["payment_mandate"]
        open_payment = mandate["open_payment_authorization"]
        closed_payment = mandate["closed_payment_authorization"]
        for authorization in (checkout, closed_payment):
            self.assertEqual(authorization["checkout_binding"], expected_binding)
        for key in ("operation_id", "checkout_id", "seller", "amount_cents", "currency"):
            self.assertEqual(closed_payment[key], intent[key], key)
        self.assertEqual(checkout["operation_id"], intent["operation_id"])
        self.assertEqual(checkout["checkout_id"], intent["checkout_id"])
        self.assertEqual(open_payment["initial_grant"], original_grant)
        self.assertEqual(open_payment["signature"], original_grant["signature"])
        self.assertNotIn("checkout_binding", open_payment)
        self.assertEqual(payment["events"][-1]["request"], mandate)
        submitted = self.to_step(payment, 6)
        body = submitted["events"][-1]["request"]["body"]
        self.assertEqual(body["intent"], intent)
        self.assertEqual(body["closed_checkout_authorization"], checkout)
        self.assertEqual(body["initial_grant"], original_grant)
        self.assertEqual(submitted["grant"], original_grant)
        self.assertEqual(original_grant["max_total_cents"], 30000)
        self.assertEqual(intent["amount_cents"], 28000)
        self.assertNotEqual(checkout["signature"], original_grant["signature"])


class PurchaseHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-purchase-http-test-")
        self.engine = Engine(self.directory.name)
        self.server = make_server(self.engine, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.engine.close()
        self.directory.cleanup()

    def request(self, method, path, body=None, *, raw=None, headers=None):
        request_headers = {"Content-Type": "application/json", "Origin": self.origin}
        request_headers.update(headers or {})
        data = raw if raw is not None else json.dumps(body).encode("utf-8") if body is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=data, headers=request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def create(self):
        status, state = self.request("POST", "/api/runs", {
            "scenario": "success", "budget_cents": 30000, "quantity": 2,
        })
        self.assertEqual(status, 201)
        return state

    def test_create_get_and_stale_revision_return_current_state(self):
        state = self.create()
        status, loaded = self.request("GET", f"/api/runs/{state['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(loaded["revision"], 0)
        route = f"/api/runs/{state['id']}/advance"
        status, advanced = self.request("POST", route, {"expected_revision": 0})
        self.assertEqual(status, 200)
        status, conflict = self.request("POST", route, {"expected_revision": 0})
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current"]["revision"], advanced["revision"])
        self.assertEqual(conflict["current"]["id"], state["id"])

    def test_malformed_json_and_body_shapes_are_rejected(self):
        for raw in (b"{", b"[]", b"null", b'"text"'):
            with self.subTest(raw=raw):
                status, result = self.request("POST", "/api/runs", raw=raw)
                self.assertEqual(status, 400)
                self.assertIn("error", result)
        state = self.create()
        route = f"/api/runs/{state['id']}/advance"
        for body in ({}, {"expected_revision": True}, {"expected_revision": -1},
                     {"expected_revision": 0, "extra": "untrusted"}):
            with self.subTest(body=body):
                status, _ = self.request("POST", route, body)
                self.assertEqual(status, 400)
        self.assertEqual(self.engine.get(state["id"])["revision"], 0)

    def test_invalid_mission_inputs_are_rejected(self):
        for override in (
            {"scenario": "unknown"}, {"scenario": []}, {"budget_cents": True},
            {"budget_cents": -1}, {"budget_cents": 28000.5},
            {"quantity": 0}, {"quantity": True}, {"extra": "untrusted"},
        ):
            with self.subTest(override=override):
                body = {"scenario": "success", "budget_cents": 30000, "quantity": 2, **override}
                status, result = self.request("POST", "/api/runs", body)
                self.assertEqual(status, 400)
                self.assertIn("error", result)

    def test_cross_origin_and_cross_site_posts_cannot_advance(self):
        state = self.create()
        route = f"/api/runs/{state['id']}/advance"
        for headers in (
            {"Origin": "https://untrusted.example"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Host": "untrusted.example"},
        ):
            with self.subTest(headers=headers):
                status, _ = self.request("POST", route, {"expected_revision": 0}, headers=headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.engine.get(state["id"])["revision"], 0)

    def test_non_json_post_and_invalid_host_get_are_rejected(self):
        status, _ = self.request("POST", "/api/runs", raw=b"{}", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _ = self.request("GET", "/api/config", headers={"Host": "untrusted.example"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
