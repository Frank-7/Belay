from __future__ import annotations

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from purchase_simulator.engine import DemoError, Engine
from purchase_simulator.mission_control import (
    MAX_PAYMENT_USD_CENTS,
    STARTING_USDC_UNITS,
    MissionEngine,
)
from purchase_simulator.server import make_server


class MissionEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-mission-test-")
        self.engine = MissionEngine(self.directory.name)

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def finish(self, state):
        while state["can_advance"]:
            state = self.engine.advance(state["id"], state["revision"])
        return state

    def to_status(self, state, status):
        while state["status"] != status:
            self.assertTrue(state["can_advance"])
            state = self.engine.advance(state["id"], state["revision"])
        return state

    def rewrite_state(self, state, change):
        with closing(sqlite3.connect(self.engine.path)) as db, db:
            raw = json.loads(
                db.execute(
                    "SELECT state_json FROM missions WHERE id=?", (state["id"],)
                ).fetchone()[0]
            )
            change(raw)
            db.execute(
                "UPDATE missions SET state_json=? WHERE id=?",
                (json.dumps(raw, sort_keys=True, separators=(",", ":")), state["id"]),
            )

    def test_representative_requests_extract_without_inventing_fields(self):
        cases = (
            (
                "Pay my $168 GEICO premium for policy AUTO-2048 by Friday",
                "insurance",
                "GEICO",
                16_800,
                "AUTO-2048",
            ),
            (
                "Pay invoice INV-1042 for $1,250 to Acme Design by September 30",
                "invoice",
                "Acme Design",
                125_000,
                "INV-1042",
            ),
            (
                "Pay $240 in federal estimated tax to the IRS for Q3-2026 by October 15",
                "tax",
                "Internal Revenue Service",
                24_000,
                "Q3-2026",
            ),
            (
                "Buy two concert tickets for $200 from Northstar Tickets",
                "ticket",
                "Northstar Tickets",
                20_000,
                "",
            ),
        )
        for request, category, payee, amount, reference in cases:
            with self.subTest(category=category):
                state = self.engine.analyze(request)
                self.assertEqual(state["plan"]["category"], category)
                self.assertEqual(state["plan"]["payee"], payee)
                self.assertEqual(state["plan"]["amount_usd_cents"], amount)
                self.assertEqual(state["plan"]["maximum_usd_cents"], amount)
                self.assertEqual(state["plan"]["reference"], reference)
                self.assertEqual(state["missing_fields"], [])
                self.assertEqual(state["status"], "ready")

    def test_unknown_request_returns_questions_instead_of_guesses(self):
        state = self.engine.analyze("Please handle this payment")
        self.assertEqual(state["plan"]["category"], "purchase")
        self.assertEqual(state["plan"]["payee"], "")
        self.assertIsNone(state["plan"]["amount_usd_cents"])
        self.assertEqual(
            [item["field"] for item in state["missing_fields"]],
            ["payee", "amount_usd_cents"],
        )
        self.assertFalse(state["can_authorize"])
        self.assertFalse(state["can_advance"])
        self.assertEqual(state["ledger"], [])

        unrelated_brand = self.engine.analyze("Pay $100 for a report about GEICO")
        self.assertEqual(unrelated_brand["plan"]["payee"], "")
        self.assertFalse(unrelated_brand["can_authorize"])

        for request in (
            "Buy two tickets to Taylor Swift for $200",
            "Book a flight to Paris for $500",
            "Buy a train ticket to Boston for $70",
            "Pay $100 to account 12345",
        ):
            with self.subTest(request=request):
                mission = self.engine.analyze(request)
                self.assertEqual(mission["plan"]["payee"], "")
                self.assertFalse(mission["can_authorize"])

    def test_category_and_known_payee_matching_use_word_boundaries(self):
        state = self.engine.analyze("Buy a first-aid watermelon kit for $20 from Acme")
        self.assertEqual(state["plan"]["category"], "purchase")
        self.assertEqual(state["plan"]["payee"], "Acme")
        self.assertNotEqual(state["plan"]["payee"], "Internal Revenue Service")

        plural_cases = {
            "Pay my federal taxes": "tax",
            "Pay these invoices": "invoice",
            "Pay my utility bills": "bill",
            "Buy two tickets": "ticket",
            "Renew my subscriptions": "subscription",
            "Send transfers to the team": "transfer",
        }
        for request, expected in plural_cases.items():
            with self.subTest(request=request):
                self.assertEqual(self.engine.analyze(request)["plan"]["category"], expected)

        explicit = self.engine.analyze(
            "Pay invoice INV-2040 for $325 to Northstar Labs by October 3"
        )
        self.assertEqual(explicit["plan"]["category"], "invoice")
        self.assertEqual(explicit["plan"]["payee"], "Northstar Labs")

        accounting = self.engine.analyze(
            "Pay my accountant invoice INV-TAX-17 for $500 to Smith Tax Advisors "
            "for tax preparation"
        )
        self.assertEqual(accounting["plan"]["category"], "invoice")
        self.assertEqual(accounting["plan"]["reference"], "INV-TAX-17")

        person = self.engine.analyze("Pay $20 to Bill Gates")
        self.assertEqual(person["plan"]["category"], "purchase")
        self.assertEqual(person["plan"]["payee"], "Bill Gates")

    def test_comma_containing_legal_payees_are_never_truncated(self):
        for request, expected in (
            ("Pay $20 to Acme, Inc.", "Acme, Inc."),
            ("Pay $20 to Johnson, Smith & Co.", "Johnson, Smith & Co."),
            ("Pay $20 to Acme, Inc. by Friday", "Acme, Inc."),
        ):
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertEqual(state["plan"]["payee"], expected)
                self.assertTrue(state["can_authorize"])
                authorized = self.engine.authorize(state["id"], state["revision"])
                self.assertEqual(authorized["grant"]["payee"], expected)

    def test_maximum_only_and_ambiguous_amounts_require_an_exact_amount(self):
        for request in (
            "Pay up to $500 to Acme",
            "Pay up to $500 dollars to Acme",
            "Pay no more than $500 USD to Acme",
            "Pay a maximum of USD 500 USD to Acme",
        ):
            with self.subTest(request=request):
                maximum_only = self.engine.analyze(request)
                self.assertIsNone(maximum_only["plan"]["amount_usd_cents"])
                self.assertEqual(maximum_only["plan"]["maximum_usd_cents"], 50_000)
                self.assertIn("amount_usd_cents", {
                    item["field"] for item in maximum_only["missing_fields"]
                })

        ambiguous = self.engine.analyze("Pay either $100 or $120 to Acme")
        self.assertIsNone(ambiguous["plan"]["amount_usd_cents"])
        self.assertEqual(ambiguous["plan"]["maximum_usd_cents"], None)
        self.assertTrue(ambiguous["plan"]["review_notes"])

    def test_required_reference_is_not_invented_from_normal_grammar(self):
        for request in (
            "Pay invoice for $100 to Acme",
            "Pay my GEICO policy for $168",
            "Pay invoice number for $100 to Acme",
            "Pay invoice: for $100 to Acme",
            "Pay bill # due for $50 to Acme",
        ):
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertEqual(state["plan"]["reference"], "")
                self.assertIn(
                    "reference",
                    {item["field"] for item in state["missing_fields"]},
                )
                self.assertFalse(state["can_authorize"])

        explicit = self.engine.analyze(
            "Pay invoice INV-2040 for $325 to Northstar Labs"
        )
        self.assertEqual(explicit["plan"]["reference"], "INV-2040")

    def test_money_range_is_explicit_and_exact_limit_is_allowed(self):
        accepted = self.engine.analyze("Pay $25,000 to Acme")
        self.assertEqual(
            accepted["plan"]["amount_usd_cents"], MAX_PAYMENT_USD_CENTS
        )
        for request in (
            "Pay $0 to Acme",
            "Pay $25,000.01 to Acme",
            "Pay $99999 to Acme",
        ):
            with self.subTest(request=request), self.assertRaises(DemoError) as stopped:
                self.engine.analyze(request)
            self.assertIn("greater than $0", str(stopped.exception))

        for request in (
            "Pay $12.345 to Acme",
            "Pay $25.001k to Acme",
            "Pay USD 8.999 to Acme",
            "Pay $1,2 to Acme",
        ):
            with self.subTest(request=request), self.assertRaises(DemoError):
                self.engine.analyze(request)

    def test_money_tokens_reject_ambiguous_suffixes_without_partial_parsing(self):
        accepted = {
            "Pay $25k to Acme": 2_500_000,
            "Pay $25 K to Acme": 2_500_000,
            "Pay $20.00 USD to Acme": 2_000,
            "Pay 20 dollars to Acme": 2_000,
        }
        for request, amount in accepted.items():
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertEqual(state["plan"]["amount_usd_cents"], amount)
                self.assertTrue(state["can_authorize"])

        for request in (
            "Pay $20 Kindle to Acme",
            "Pay $20 K-pop to Acme",
            "Pay $20M to Acme",
            "Pay $20million to Acme",
            "Pay $20abc to Acme",
        ):
            with self.subTest(request=request), self.assertRaises(DemoError) as stopped:
                self.engine.analyze(request)
            self.assertIn("Ambiguous amount suffix", str(stopped.exception))

    def test_reference_tokens_are_captured_whole_instead_of_as_prefixes(self):
        for request, expected in (
            ("Pay invoice 2026/1042 for $20 to Acme", "2026/1042"),
            ("Pay invoice 123.45 for $20 to Acme", "123.45"),
            ("Pay policy 123/456 for $20 to GEICO", "123/456"),
        ):
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertEqual(state["plan"]["reference"], expected)
                self.assertNotIn(
                    "reference", {item["field"] for item in state["missing_fields"]}
                )

    def test_plan_revision_changes_only_when_reviewed_plan_changes(self):
        state = self.engine.analyze("Pay $20 to Acme")
        self.assertEqual(state["plan_revision"], 1)
        state = self.engine.update_details(
            state["id"], state["revision"], {"payee": "Acme"}
        )
        self.assertEqual(state["plan_revision"], 1)
        state = self.engine.update_details(
            state["id"], state["revision"], {"category": "invoice"}
        )
        self.assertEqual(state["plan_revision"], 2)
        state = self.engine.update_details(
            state["id"], state["revision"], {"reference": "INV-20"}
        )
        self.assertEqual(state["plan_revision"], 3)
        state = self.engine.authorize(state["id"], state["revision"])
        self.assertEqual(state["plan_revision"], 3)
        state = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(state["plan_revision"], 3)

    def test_missing_insurance_details_can_be_completed_and_paid_once(self):
        state = self.engine.analyze("Pay my insurance premium")
        self.assertEqual(
            [item["field"] for item in state["missing_fields"]],
            ["payee", "amount_usd_cents", "reference"],
        )
        state = self.engine.update_details(
            state["id"],
            state["revision"],
            {
                "payee": "GEICO",
                "amount_usd_cents": 16_800,
                "maximum_usd_cents": 16_800,
                "reference": "AUTO-2048",
                "due_date": "Friday",
            },
        )
        self.assertTrue(state["can_authorize"])
        state = self.engine.authorize(state["id"], state["revision"])
        self.assertEqual(state["grant"]["amount_usd_cents"], 16_800)
        final = self.finish(state)

        self.assertEqual(final["status"], "complete")
        self.assertTrue(final["terminal"])
        self.assertEqual(final["money"]["payment_hold_usdc_units"], 0)
        self.assertEqual(final["money"]["provider_in_transit_usdc_units"], 0)
        self.assertEqual(final["money"]["payee_received_usd_cents"], 16_800)
        self.assertEqual(
            final["money"]["customer_available_usdc_units"] + 16_800 * 10_000,
            STARTING_USDC_UNITS,
        )
        self.assertEqual(
            [entry["kind"] for entry in final["ledger"]],
            ["payment_hold", "provider_dispatch", "usdc_to_usd_payout"],
        )
        self.assertEqual(final["provider_payment"]["attempt_count"], 1)
        self.assertEqual(final["receipt"]["payment"]["status"], "simulated_paid")
        self.assertEqual(final["receipt"]["domain_outcome"]["status"], "not_verified")
        self.assertEqual(
            final["receipt"]["domain_outcome"]["label"],
            "Premium applied to policy",
        )
        self.assertEqual(final["states"]["domain_confirmation"], "external_not_verified")

    def test_authorization_rejects_exact_amount_above_reviewed_maximum(self):
        state = self.engine.analyze("Pay $100, no more than $90, to Acme")
        self.assertEqual(state["plan"]["amount_usd_cents"], 10_000)
        self.assertEqual(state["plan"]["maximum_usd_cents"], 9_000)
        with self.assertRaises(DemoError) as stopped:
            self.engine.authorize(state["id"], state["revision"])
        self.assertIn("exceeds", str(stopped.exception))
        self.assertEqual(self.engine.get(state["id"])["ledger"], [])

    def test_stale_revision_returns_current_state_without_mutation(self):
        state = self.engine.analyze("Pay $20 to Acme")
        authorized = self.engine.authorize(state["id"], state["revision"])
        with self.assertRaises(DemoError) as stopped:
            self.engine.authorize(state["id"], state["revision"])
        self.assertEqual(stopped.exception.status, 409)
        self.assertEqual(stopped.exception.current["revision"], authorized["revision"])
        self.assertEqual(stopped.exception.current["ledger"], [])

    def test_changed_plan_after_authorization_is_blocked_before_value_moves(self):
        state = self.engine.analyze("Pay $20 to Acme")
        state = self.engine.authorize(state["id"], state["revision"])

        def change_amount(raw):
            raw["plan"]["amount_usd_cents"] = 2_100

        self.rewrite_state(state, change_amount)
        final = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(final["status"], "blocked")
        self.assertEqual(final["ledger"], [])
        self.assertEqual(
            final["money"]["customer_available_usdc_units"], STARTING_USDC_UNITS
        )
        failed = {
            check["name"]
            for check in final["policy_decision"]["checks"]
            if not check["passed"]
        }
        self.assertIn("Plan unchanged", failed)
        self.assertIn("Amount matches", failed)
        self.assertIn("before any funds were reserved or sent", final["user_message"])

    def test_changed_category_after_authorization_is_blocked(self):
        state = self.engine.analyze("Pay $20 to Acme")
        state = self.engine.authorize(state["id"], state["revision"])

        def change_category(raw):
            raw["plan"]["category"] = "tax"

        self.rewrite_state(state, change_category)
        final = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(final["status"], "blocked")
        self.assertEqual(final["ledger"], [])
        self.assertIn("Plan unchanged", {
            check["name"]
            for check in final["policy_decision"]["checks"]
            if not check["passed"]
        })

    def test_changed_signed_intent_returns_hold_and_never_dispatches(self):
        state = self.engine.analyze("Pay $20 to Acme")
        state = self.engine.authorize(state["id"], state["revision"])
        state = self.to_status(state, "signed")

        def change_intent(raw):
            raw["signed_intent"]["destination_usd_cents"] = 2_100

        self.rewrite_state(state, change_intent)
        final = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(final["status"], "blocked")
        self.assertEqual(final["money"]["payment_hold_usdc_units"], 0)
        self.assertEqual(
            final["money"]["customer_available_usdc_units"], STARTING_USDC_UNITS
        )
        self.assertEqual(final["provider_payment"], None)
        self.assertEqual(
            [entry["kind"] for entry in final["ledger"]],
            ["payment_hold", "integrity_hold_return"],
        )
        self.assertIn("was returned; nothing was dispatched", final["user_message"])

    def test_expired_grant_is_checked_at_every_pre_dispatch_gate(self):
        for target in ("authorized", "checked", "held", "signed"):
            with self.subTest(target=target), patch(
                "purchase_simulator.mission_control.time.time", return_value=1_000
            ):
                state = self.engine.analyze("Pay $20 to Acme")
                state = self.engine.authorize(state["id"], state["revision"])
                state = self.to_status(state, target)
            with patch(
                "purchase_simulator.mission_control.time.time", return_value=2_800
            ):
                final = self.engine.advance(state["id"], state["revision"])
            self.assertEqual(final["status"], "blocked")
            self.assertEqual(final["provider_payment"], None)
            self.assertEqual(final["money"]["payment_hold_usdc_units"], 0)
            self.assertEqual(
                final["money"]["customer_available_usdc_units"],
                STARTING_USDC_UNITS,
            )
            self.assertEqual(final["title"], "Authorization expired")
            if target in {"held", "signed"}:
                self.assertIn("was returned; nothing was dispatched", final["user_message"])
            else:
                self.assertIn("before any funds were reserved or sent", final["user_message"])

    def test_sensitive_values_are_redacted_before_disk_and_audit(self):
        request = (
            "Pay $50 to Acme for account 123456789. "
            "Use card 4111 1111 1111 1111, SSN 123-45-6789, "
            "and API key sk_live_supersecret123"
        )
        state = self.engine.analyze(request)
        self.assertTrue(state["sensitive_input_redacted"])
        self.assertGreaterEqual(len(state["redaction_categories"]), 3)
        encoded = json.dumps(state, sort_keys=True)
        with closing(sqlite3.connect(self.engine.path)) as db:
            stored = db.execute(
                "SELECT state_json FROM missions WHERE id=?", (state["id"],)
            ).fetchone()[0]
        for secret in (
            "123456789",
            "4111 1111 1111 1111",
            "123-45-6789",
            "supersecret123",
        ):
            self.assertNotIn(secret, encoded)
            self.assertNotIn(secret, stored)
        self.assertIn("[REDACTED]", encoded)
        self.assertIn("ending 1111", state["request_text"])

    def test_reference_is_masked_in_technical_audit(self):
        state = self.engine.analyze("Pay $20 invoice INV-1042 to Acme")
        state = self.engine.authorize(state["id"], state["revision"])
        audit_plan = state["events"][-1]["backend"]["request"]["reviewed_plan"]
        self.assertEqual(audit_plan["reference"], "••••1042")
        self.assertEqual(state["plan"]["reference"], "INV-1042")

    def test_same_revision_dispatchs_once_under_concurrency(self):
        state = self.engine.analyze("Pay $20 to Acme")
        state = self.engine.authorize(state["id"], state["revision"])
        state = self.to_status(state, "signed")
        barrier = threading.Barrier(2)

        def dispatch():
            barrier.wait(timeout=5)
            try:
                return self.engine.advance(state["id"], state["revision"])
            except DemoError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _unused: dispatch(), range(2)))
        accepted = [result for result in results if isinstance(result, dict)]
        rejected = [result for result in results if isinstance(result, DemoError)]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].status, 409)
        current = self.engine.get(state["id"])
        self.assertEqual(current["status"], "dispatched")
        self.assertEqual(current["provider_payment"]["attempt_count"], 1)
        self.assertEqual(
            [entry["kind"] for entry in current["ledger"]].count(
                "provider_dispatch"
            ),
            1,
        )

    def test_recipient_display_after_dispatch_comes_from_signed_evidence(self):
        state = self.engine.analyze("Pay $20 to Acme, Inc.")
        state = self.engine.authorize(state["id"], state["revision"])
        original_payee_id = state["grant"]["payee_id"]
        state = self.to_status(state, "dispatched")

        def change_display_plan(raw):
            raw["plan"]["payee"] = "Attacker LLC"
            raw["plan"]["payee_id"] = "beneficiary_attacker"

        self.rewrite_state(state, change_display_plan)
        paid = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(paid["status"], "paid")
        self.assertIn("Acme, Inc.", paid["user_message"])
        self.assertNotIn("Attacker", paid["user_message"])
        self.assertEqual(paid["provider_payment"]["payee_id"], original_payee_id)
        self.assertEqual(paid["provider_payment"]["attempt_count"], 1)

        reviewed = self.engine.advance(paid["id"], paid["revision"])
        self.assertEqual(reviewed["status"], "review_required")
        self.assertEqual(reviewed["receipt"], None)
        self.assertEqual(reviewed["provider_payment"]["attempt_count"], 1)

    def test_receipt_refuses_mismatched_paid_evidence_without_repaying(self):
        state = self.engine.analyze("Pay $20 to Acme")
        state = self.engine.authorize(state["id"], state["revision"])
        state = self.to_status(state, "paid")

        def change_amount(raw):
            raw["plan"]["amount_usd_cents"] = 2_100

        self.rewrite_state(state, change_amount)
        final = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(final["status"], "review_required")
        self.assertEqual(final["receipt"], None)
        self.assertEqual(final["provider_payment"]["status"], "paid")
        self.assertEqual(final["provider_payment"]["attempt_count"], 1)
        self.assertEqual(
            [entry["kind"] for entry in final["ledger"]].count(
                "usdc_to_usd_payout"
            ),
            1,
        )

    def test_receipt_domain_claims_come_from_fixed_category_rules(self):
        state = self.engine.analyze(
            "Pay $240 in federal estimated tax to the IRS for Q3-2026"
        )
        state = self.engine.authorize(state["id"], state["revision"])
        state = self.to_status(state, "paid")

        def overclaim(raw):
            raw["plan"]["domain_confirmation_label"] = "Tax return filed"
            raw["plan"]["confirmation_scope"] = "Everything is complete"

        self.rewrite_state(state, overclaim)
        final = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(final["status"], "complete")
        self.assertEqual(
            final["receipt"]["domain_outcome"]["label"], "Tax account posting"
        )
        self.assertEqual(final["receipt"]["domain_outcome"]["status"], "not_verified")
        self.assertNotIn("Everything is complete", json.dumps(final["receipt"]))

    def test_state_survives_restart_and_database_file_is_releasable(self):
        state = self.engine.analyze("Pay $20 to Acme")
        self.engine.close()
        self.engine = MissionEngine(self.directory.name)
        loaded = self.engine.get(state["id"])
        self.assertEqual(loaded["request_digest"], state["request_digest"])

        separate_dir = Path(self.directory.name) / "clean-close"
        separate = MissionEngine(separate_dir)
        separate.analyze("Pay $20 to Acme")
        database_path = separate.path
        separate.close()
        database_path.unlink()
        self.assertFalse(database_path.exists())


class MissionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-mission-http-")
        self.purchase_engine = Engine(self.directory.name)
        self.server = make_server(self.purchase_engine, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.purchase_engine.close()
        self.directory.cleanup()

    def request(self, method, path, body=None, *, raw=None, headers=None):
        request_headers = {"Content-Type": "application/json", "Origin": self.origin}
        request_headers.update(headers or {})
        data = (
            raw
            if raw is not None
            else json.dumps(body).encode("utf-8")
            if body is not None
            else None
        )
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        try:
            connection.request(method, path, body=data, headers=request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_full_http_contract_and_stale_conflict(self):
        status, config = self.request("GET", "/api/mission/config")
        self.assertEqual(status, 200)
        self.assertEqual(config["max_payment_usd_cents"], MAX_PAYMENT_USD_CENTS)

        status, state = self.request(
            "POST", "/api/missions/analyze", {"request": "Pay my tax bill"}
        )
        self.assertEqual(status, 201)
        status, state = self.request(
            "POST",
            f"/api/missions/{state['id']}/details",
            {
                "expected_revision": state["revision"],
                "fields": {
                    "payee": "Internal Revenue Service",
                    "amount_usd_cents": 24_000,
                    "reference": "Q3-2026",
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(state["can_authorize"])
        status, authorized = self.request(
            "POST",
            f"/api/missions/{state['id']}/authorize",
            {"expected_revision": state["revision"]},
        )
        self.assertEqual(status, 200)
        status, conflict = self.request(
            "POST",
            f"/api/missions/{state['id']}/authorize",
            {"expected_revision": state["revision"]},
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current"]["revision"], authorized["revision"])

        status, loaded = self.request("GET", f"/api/missions/{state['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(loaded["id"], state["id"])

    def test_http_rejects_bad_shapes_inputs_and_origins(self):
        for body in (
            {},
            {"request": "Pay $20 to Acme", "extra": True},
            {"request": True},
        ):
            with self.subTest(body=body):
                status, result = self.request(
                    "POST", "/api/missions/analyze", body
                )
                self.assertEqual(status, 400)
                self.assertIn("error", result)

        status, state = self.request(
            "POST", "/api/missions/analyze", {"request": "Pay $20 to Acme"}
        )
        self.assertEqual(status, 201)
        for body in (
            {"expected_revision": True},
            {"expected_revision": -1},
            {"expected_revision": 0, "extra": "x"},
        ):
            with self.subTest(body=body):
                status, result = self.request(
                    "POST", f"/api/missions/{state['id']}/authorize", body
                )
                self.assertEqual(status, 400)
                self.assertIn("error", result)

        status, _result = self.request(
            "POST",
            "/api/missions/analyze",
            raw=b"",
            headers={"Origin": "https://untrusted.example"},
        )
        self.assertEqual(status, 403)
        status, _result = self.request("GET", "/api/missions/not-an-id")
        self.assertEqual(status, 404)

    def test_server_close_closes_mission_engine_and_releases_database(self):
        mission_engine = self.server.mission_engine
        status, _state = self.request(
            "POST", "/api/missions/analyze", {"request": "Pay $20 to Acme"}
        )
        self.assertEqual(status, 201)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertTrue(mission_engine.closed)
        with self.assertRaises(DemoError) as stopped:
            mission_engine.config()
        self.assertEqual(stopped.exception.status, 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
