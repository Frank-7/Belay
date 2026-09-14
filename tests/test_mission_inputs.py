"""Input regressions for exact payment intent and credential persistence."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing

from purchase_simulator.engine import DemoError
from purchase_simulator.mission_control import MAX_REQUEST_LENGTH, MissionEngine


class MissionInputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-mission-input-")
        self.engine = MissionEngine(self.directory.name)

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def assert_canary_absent(self, canary: str, state: dict | None = None):
        """Check user responses, audit records, stored JSON, and SQLite files."""

        if state is not None:
            self.assertNotIn(canary, json.dumps(state))
            self.assertNotIn(canary, json.dumps(self.engine.get(state["id"])))
            self.assertNotIn(canary, json.dumps(state["events"]))
        with closing(sqlite3.connect(self.engine.path)) as db:
            for (stored,) in db.execute("SELECT state_json FROM missions"):
                self.assertNotIn(canary, stored)
        for path in self.engine.data_dir.glob("*.sqlite3*"):
            self.assertNotIn(canary.encode(), path.read_bytes(), str(path))

    def test_limit_phrases_require_an_exact_payment(self):
        requests = (
            "Pay at most $500 to Acme",
            "Pay a maximum amount of $500 to Acme",
            "Pay with a budget of $500 to Acme",
            "Pay to Acme. My budget is $500",
            "Pay to Acme. Budget: $500",
            "Pay to Acme with a spending limit of $500",
            "Pay no more than $500 to Acme",
            "Pay an amount not exceeding $500 to Acme",
            "Pay $500 maximum to Acme",
            "Pay to Acme within a $500 budget",
            "Pay $500 or less to Acme",
        )
        for request in requests:
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertIsNone(state["plan"]["amount_usd_cents"])
                self.assertEqual(state["plan"]["maximum_usd_cents"], 50_000)
                self.assertFalse(state["can_authorize"])
                self.assertIn("amount_usd_cents", [f["field"] for f in state["missing_fields"]])
                with self.assertRaises(DemoError):
                    self.engine.authorize(state["id"], state["revision"])
                self.assertEqual(self.engine.get(state["id"])["ledger"], [])

    def test_exact_amount_and_separate_ceiling_are_preserved(self):
        for request in (
            "Pay $300 to Acme. My maximum amount is $500",
            "Budget: $500. Pay $300 to Acme",
            "Pay $300 to Acme with a maximum of $500",
            "Pay $300 to Acme, no more than $500",
            "Pay $300 to Acme. Budget $500, spending limit $400",
        ):
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertEqual(state["plan"]["amount_usd_cents"], 30_000)
                self.assertEqual(
                    state["plan"]["maximum_usd_cents"],
                    40_000 if "limit $400" in request else 50_000,
                )
                self.assertTrue(state["can_authorize"])

    def test_limits_do_not_override_exact_amount_or_relax_authorization(self):
        state = self.engine.analyze("Pay $600 to Acme. Budget: $500")
        self.assertEqual(state["plan"]["amount_usd_cents"], 60_000)
        self.assertEqual(state["plan"]["maximum_usd_cents"], 50_000)
        with self.assertRaisesRegex(DemoError, "exceeds"):
            self.engine.authorize(state["id"], state["revision"])

    def test_amounts_accept_sentence_punctuation_without_partial_decimals(self):
        for request in ("Pay to Acme $300.", "Pay USD 300. To Acme"):
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertEqual(state["plan"]["amount_usd_cents"], 30_000)
        for request in ("Pay $300.123 to Acme", "Pay USD 300.123 to Acme"):
            with self.subTest(request=request), self.assertRaises(DemoError):
                self.engine.analyze(request)

    def test_ranges_minima_and_estimates_are_not_exact_payments(self):
        for request in (
            "Pay about $500 to Acme",
            "Pay approximately $500 to Acme",
            "Pay at least $500 to Acme",
            "Pay a minimum amount of $500 to Acme",
            "Pay $500 or more to Acme",
            "Pay between $300 and $500 to Acme",
            "Pay $300 to $500 to Acme",
            "Pay $300 or $500 to Acme",
            "Pay at most $300 or $500 to Acme",
        ):
            with self.subTest(request=request):
                state = self.engine.analyze(request)
                self.assertIsNone(state["plan"]["amount_usd_cents"])
                self.assertFalse(state["can_authorize"])

    def test_credentials_with_adjacent_separators_are_removed_everywhere(self):
        for label in ("password", "API key", "api_key", "access-token", "private_key", "secret"):
            for separator in ("=", ":", " = ", " is ", " "):
                with self.subTest(label=label, separator=separator):
                    canary = "FAKEcredentialCanary_aB!$+="
                    state = self.engine.analyze(f"Pay $50 to Acme. {label}{separator}{canary}")
                    self.assertTrue(state["sensitive_input_redacted"])
                    self.assertIn("credential", state["redaction_categories"])
                    self.assert_canary_absent(canary, state)

    def test_quoted_credentials_and_bearer_values_are_removed(self):
        canary = "FAKE secret with spaces and punctuation !,;="
        for credential in (f'password="{canary}"', f"secret:'{canary}'"):
            with self.subTest(credential=credential):
                state = self.engine.analyze(f"Pay $50 to Acme. {credential}")
                self.assert_canary_absent(canary, state)
                self.assertNotIn("punctuation", json.dumps(state))
        canary = "FAKEBearerCanaryZ!_a-b"
        state = self.engine.analyze(f"Pay $50 to Acme. Bearer {canary}")
        self.assert_canary_absent(canary, state)

    def test_private_key_blocks_and_unclosed_blocks_are_removed(self):
        for label in ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "ENCRYPTED PRIVATE KEY", "OPENSSH PRIVATE KEY"):
            for include_end in (True, False):
                with self.subTest(label=label, include_end=include_end):
                    canary = "FAKEPrivateKeyCanaryBase64Value"
                    key = f"-----BEGIN {label}-----\n{canary}\n"
                    if include_end:
                        key += f"-----END {label}-----"
                    state = self.engine.analyze(f"Pay $50 to Acme. {key}")
                    self.assertTrue(state["sensitive_input_redacted"])
                    self.assertIn("private_key", state["redaction_categories"])
                    self.assert_canary_absent(canary, state)

    def test_editable_fields_redact_before_truncating_private_keys(self):
        canary = "FAKELongPrivateKeyCanary"
        long_key = "-----BEGIN PRIVATE KEY-----\n" + (canary + "\n") * 70
        long_key += "-----END PRIVATE KEY-----"
        state = self.engine.analyze("Pay $50 to Acme")
        state = self.engine.update_details(
            state["id"], state["revision"], {"description": long_key, "reference": "password=FAKEreferenceSecret"}
        )
        self.assertEqual(state["plan"]["description"], "[REDACTED PRIVATE KEY]")
        self.assert_canary_absent(canary, state)
        self.assert_canary_absent("FAKEreferenceSecret", state)

    def test_request_length_boundary_does_not_persist_partial_private_keys(self):
        canary = "FAKEBoundaryPrivateKeyCanary"
        prefix = "Pay $50 to Acme. -----BEGIN PRIVATE KEY----- " + canary + " "
        request = prefix + "A" * (MAX_REQUEST_LENGTH - len(prefix))
        state = self.engine.analyze(request)
        self.assert_canary_absent(canary, state)

        rejected_canary = "FAKERejectedPrivateKeyCanary"
        request = "Pay $50 to Acme. -----BEGIN PRIVATE KEY----- " + rejected_canary
        request += "A" * MAX_REQUEST_LENGTH + "-----END PRIVATE KEY-----"
        with self.assertRaises(DemoError) as caught:
            self.engine.analyze(request)
        self.assertNotIn(rejected_canary, str(caught.exception))
        self.assert_canary_absent(rejected_canary)


if __name__ == "__main__":
    unittest.main()
