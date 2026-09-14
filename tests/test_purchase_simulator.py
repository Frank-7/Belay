"""Focused regressions for the fictional Belay v0.3 investor MVP.

The HTTP checks use a real loopback server. USDC, conversion, merchant payout,
delivery evidence and protection are local fixtures; no external service or
real money is used.
"""

from __future__ import annotations

import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from purchase_simulator.engine import SCHEMA_VERSION, DemoError, Engine  # noqa: E402
from purchase_simulator.server import make_server  # noqa: E402

USDC = 1_000_000
CUSTOMER_START = 300 * USDC
ORDER_COST = 200 * USDC
ORDER_USD_CENTS = 20_000
RESERVE_START = 1_000 * USDC
COMBINED_COVER = 300 * USDC


class PurchaseEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-v03-purchase-test-")
        self.engine = Engine(self.directory.name)

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def create(self, scenario="success", budget=30_000):
        return self.engine.create(scenario, budget, quantity=2)

    def to_step(self, state, wanted):
        for _ in range(20):
            if state["step"] >= wanted or state["terminal"]:
                break
            state = self.engine.advance(state["id"], state["revision"])
        self.assertEqual(state["step"], wanted)
        return state

    def finish(self, state):
        for _ in range(20):
            if state["terminal"]:
                return state
            state = self.engine.advance(state["id"], state["revision"])
        self.fail("v0.3 purchase did not reach a terminal state within 20 transitions")

    def restart(self):
        self.engine.close()
        self.engine = Engine(self.directory.name)

    def ledger_kinds(self, state):
        return [entry["kind"] for entry in state["ledger"]]

    def rewrite_saved_state(self, state, mutate):
        with closing(sqlite3.connect(self.engine.path)) as db, db:
            raw = json.loads(
                db.execute(
                    "SELECT state_json FROM runs WHERE id=?", (state["id"],)
                ).fetchone()[0]
            )
            mutate(raw)
            db.execute(
                "UPDATE runs SET state_json=? WHERE id=?",
                (json.dumps(raw, sort_keys=True, separators=(",", ":")), state["id"]),
            )

    def assert_demo_value_conserved(self, state):
        """The fixed 1:1 fixture must not create or lose represented value."""

        represented = (
            state["buyer"]["available_usdc_units"]
            + state["buyer"]["held_usdc_units"]
            + state["settlement"]["provider_in_transit_usdc_units"]
            + state["settlement"]["merchant_received_usd_cents"] * 10_000
            + state["protection"]["reserve_cash_usdc_units"]
        )
        self.assertEqual(represented, CUSTOMER_START + RESERVE_START)

    def test_every_scenario_conserves_the_fixed_one_to_one_demo_value(self):
        for scenario in (
            "success",
            "payout_reply_lost",
            "non_delivery_paid",
            "quantity_violation",
            "historical_agent_error",
            "cancel_before_dispatch",
            "evidence_conflict",
        ):
            with self.subTest(scenario=scenario):
                state = self.create(scenario)
                self.assert_demo_value_conserved(state)
                for _ in range(20):
                    if state["terminal"]:
                        break
                    state = self.engine.advance(state["id"], state["revision"])
                    self.assert_demo_value_conserved(state)
                self.assertTrue(state["terminal"])

    def test_success_separates_customer_usdc_merchant_usd_and_delivery(self):
        final = self.finish(self.create())

        self.assertTrue(final["terminal"])
        self.assertEqual(final["schema_version"], SCHEMA_VERSION)
        self.assertEqual(final["entry_mode"], "live_guarded_simulation")
        self.assertEqual(final["stage"], "complete")
        self.assertEqual(final["payout_state"], "paid")
        self.assertEqual(final["delivery_state"], "verified")
        self.assertEqual(len(final["tickets"]), 2)

        outcomes = {event["stage"]: event["outcome"] for event in final["events"]}
        self.assertEqual(outcomes["payout_submitted"]["headline"], "Merchant payout processing")
        self.assertEqual(outcomes["merchant_paid"]["headline"], "Merchant paid once")
        self.assertEqual(
            outcomes["order_confirmed"]["headline"],
            "Order confirmed; delivery pending",
        )
        self.assertEqual(outcomes["delivery_check"]["headline"], "Checking ticket delivery")
        self.assertEqual(outcomes["delivered"]["headline"], "Two tickets verified")

        self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START - ORDER_COST)
        self.assertEqual(final["buyer"]["held_usdc_units"], 0)
        self.assertEqual(final["settlement"]["provider_in_transit_usdc_units"], 0)
        self.assertEqual(final["settlement"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(final["settlement"]["provider_payout_count"], 1)
        self.assertEqual(final["settlement"]["provider_attempt_count"], 1)

        self.assertEqual(final["protection"]["reserve_cash_usdc_units"], RESERVE_START)
        self.assertEqual(final["protection"]["committed_usdc_units"], 0)
        self.assertEqual(final["protection"]["pending_usdc_units"], 0)
        self.assertEqual(final["protection"]["paid_usdc_units"], 0)
        self.assertEqual(final["protection"]["available_usdc_units"], RESERVE_START)
        self.assertEqual(
            self.ledger_kinds(final),
            ["order_hold", "provider_dispatch", "conversion_and_merchant_payout"],
        )

        receipt = final["receipt"]
        self.assertEqual(receipt["instruction"]["quantity"], 2)
        self.assertEqual(receipt["purchase"]["quantity"], 2)
        self.assertEqual(receipt["payment"]["source_asset"], "USDC")
        self.assertEqual(receipt["payment"]["merchant_asset"], "USD")
        self.assertEqual(receipt["payment"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(receipt["outcome"]["remedy_usdc_units"], 0)
        settlement = final["settlement_record"]
        self.assertEqual(settlement["beneficiary_id"], "merchant_northstar_demo")
        self.assertEqual(settlement["source_asset"], "USDC")
        self.assertEqual(settlement["source_units"], ORDER_COST)
        self.assertEqual(settlement["destination_asset"], "USD")
        self.assertEqual(settlement["net_destination_units"], ORDER_USD_CENTS)

    def test_receipt_uses_persisted_settlement_instead_of_mutable_display_cache(self):
        paid = self.to_step(self.create(), 8)
        provider_reference = paid["settlement_record"]["provider_reference"]

        def forge_display_cache(raw):
            raw["payout_evidence"]["net_usd_cents"] = 99_999
            raw["payout_evidence"]["provider_reference"] = "forged"

        self.rewrite_saved_state(paid, forge_display_cache)
        final = self.finish(self.engine.get(paid["id"]))
        self.assertEqual(
            final["receipt"]["payment"]["merchant_received_usd_cents"],
            ORDER_USD_CENTS,
        )
        self.assertEqual(
            final["receipt"]["payment"]["provider_reference"], provider_reference
        )

    def test_receipt_refuses_changed_authority_or_delivery_after_payment(self):
        mutations = (
            ("grant", lambda raw: raw["grant"].__setitem__("quantity", 3)),
            ("offer", lambda raw: raw["offer"].__setitem__("total_usd_cents", 19_999)),
            ("delivery", lambda raw: raw.__setitem__("delivery_state", "not_delivered")),
            ("tickets", lambda raw: raw.__setitem__("tickets", [])),
        )
        for name, mutate in mutations:
            with self.subTest(mutation=name):
                delivered = self.to_step(self.create(), 11)
                self.rewrite_saved_state(delivered, mutate)
                with self.assertRaises(DemoError) as stopped:
                    self.engine.advance(delivered["id"], delivered["revision"])
                self.assertEqual(stopped.exception.status, 409)
                current = self.engine.get(delivered["id"])
                self.assertEqual(current["step"], 11)
                self.assertIsNone(current["receipt"])

    def test_quantity_three_is_blocked_before_every_financial_effect(self):
        final = self.finish(self.create("quantity_violation"))

        self.assertEqual(final["stage"], "policy_blocked")
        self.assertEqual(final["step"], 3)
        self.assertEqual(final["offer"]["quantity"], 3)
        self.assertFalse(final["policy_decision"]["allowed"])
        failed = {check["name"] for check in final["policy_decision"]["checks"] if not check["passed"]}
        self.assertIn("quantity", failed)
        self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
        self.assertEqual(final["buyer"]["held_usdc_units"], 0)
        self.assertEqual(final["settlement"]["provider_in_transit_usdc_units"], 0)
        self.assertEqual(final["settlement"]["merchant_received_usd_cents"], 0)
        self.assertEqual(final["settlement"]["provider_attempt_count"], 0)
        self.assertEqual(final["settlement"]["provider_payout_count"], 0)
        self.assertEqual(final["protection"]["max_usdc_units"], 0)
        self.assertEqual(final["protection"]["committed_usdc_units"], 0)
        self.assertEqual(final["protection"]["reserve_cash_usdc_units"], RESERVE_START)
        self.assertEqual(final["ledger"], [])
        self.assertEqual(final["provider"], {})

    def test_lost_payout_reply_reconciles_exact_operation_once_after_restart(self):
        unknown = self.to_step(self.create("payout_reply_lost"), 8)
        operation_id = unknown["operation_id"]
        provider_reference = unknown["provider"]["provider_reference"]

        self.assertEqual(unknown["payout_state"], "unknown")
        self.assertEqual(unknown["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(unknown["settlement"]["provider_payout_count"], 1)
        self.assertEqual(unknown["settlement"]["provider_observed_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(unknown["settlement"]["merchant_received_usd_cents"], 0)
        self.assertEqual(unknown["settlement"]["provider_in_transit_usdc_units"], ORDER_COST)
        unknown_event = unknown["events"][-1]
        self.assertFalse(unknown_event["response"]["delivered"])
        self.assertNotIn("provider_reference", unknown_event["response"])
        self.assertEqual(unknown_event["provider_observation"]["payout_state"], "paid")
        self.assertEqual(unknown_event["knowledge"]["belay"], "unknown")
        self.assertEqual(
            unknown_event["knowledge"]["safe_next_action"],
            "read_only_lookup_by_operation_id",
        )

        self.restart()
        restored = self.engine.get(unknown["id"])
        self.assertEqual(restored["operation_id"], operation_id)
        self.assertEqual(restored["payout_state"], "unknown")
        self.assertEqual(restored["settlement"]["provider_attempt_count"], 1)

        reconciled = self.engine.advance(restored["id"], restored["revision"])
        self.assertEqual(reconciled["stage"], "payout_reconciled")
        self.assertEqual(reconciled["operation_id"], operation_id)
        self.assertEqual(reconciled["provider"]["provider_reference"], provider_reference)
        self.assertEqual(reconciled["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(reconciled["settlement"]["provider_payout_count"], 1)
        self.assertEqual(reconciled["settlement"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(reconciled["settlement"]["provider_in_transit_usdc_units"], 0)
        self.assertEqual(reconciled["events"][-1]["method"], "GET")
        self.assertFalse(reconciled["events"][-1]["request"]["creates_payment"])
        self.assertEqual(reconciled["outcome"]["kind"], "safe")
        self.assertEqual(reconciled["outcome"]["headline"], "Payout reconciled: paid once")

        final = self.finish(reconciled)
        self.assertEqual(final["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(final["settlement"]["provider_payout_count"], 1)
        self.assertEqual(self.ledger_kinds(final).count("provider_dispatch"), 1)
        self.assertEqual(self.ledger_kinds(final).count("conversion_and_merchant_payout"), 1)

    def test_events_preserve_both_sides_and_exact_backend_effects(self):
        created = self.create("success")
        first = created["events"][0]
        self.assertEqual(first["stage"], "mission_authorized")
        self.assertEqual(first["revision"], 0)
        self.assertIn("two adjacent tickets", first["user_message"])
        self.assertEqual(first["technical"]["layer_id"], "authority")
        self.assertIn("control", first["technical"])
        self.assertIn("proof", first["technical"])
        self.assertIn("money_effect", first["technical"])
        self.assertIn("retry_rule", first["technical"])
        self.assertEqual(
            first["accounts_after"]["customer_available"]["units"],
            300 * USDC,
        )
        self.assertEqual(first["balance_changes"], [])
        self.assertEqual(first["ledger_keys"], [])

        admitted = self.to_step(created, 3)
        event = admitted["events"][-1]
        self.assertEqual(event["stage"], "admitted")
        self.assertEqual(event["state_before"]["funding_state"], "funded_grant")
        self.assertEqual(event["state_after"]["funding_state"], "held")
        self.assertEqual(
            {change["account"] for change in event["balance_changes"]},
            {"customer_available", "order_hold"},
        )
        self.assertEqual(event["ledger_keys"], [f"{admitted['order_id']}:hold"])
        self.assertEqual(
            event["protection_after"]["committed_usdc_units"],
            300 * USDC,
        )
        self.assertEqual(event["outcome"], admitted["outcome"])

    def test_dispatch_is_durable_before_provider_io_and_recovery_never_resubmits(self):
        signed = self.to_step(self.create(), 4)
        submit = self.engine.provider.submit

        def commit_then_interrupt(intent):
            # A separate connection sees the uncertainty and reservation before
            # the independently committing provider can receive the request.
            with closing(sqlite3.connect(self.engine.path)) as db:
                raw = json.loads(db.execute(
                    "SELECT state_json FROM runs WHERE id=?", (signed["id"],)
                ).fetchone()[0])
                self.assertEqual(raw["stage"], "dispatch_unknown")
                row = db.execute("SELECT intent_json FROM dispatch_attempts_v3 WHERE run_id=?", (signed["id"],)).fetchone()
                self.assertEqual(json.loads(row[0]), intent)
            submit(intent)
            raise RuntimeError("process interrupted after provider commit")

        with patch.object(self.engine.provider, "submit", side_effect=commit_then_interrupt):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self.engine.advance(signed["id"], signed["revision"])
        self.restart()
        unknown = self.engine.get(signed["id"])
        self.assertEqual(unknown["payout_state"], "unknown")
        self.assertEqual(unknown["buyer"]["available_usdc_units"], CUSTOMER_START - ORDER_COST)
        self.assertEqual(unknown["buyer"]["held_usdc_units"], ORDER_COST)
        self.assertEqual(unknown["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(unknown["dispatch_record"]["operation_id"], signed["operation_id"])
        with patch("purchase_simulator.engine.time.time", return_value=signed["grant"]["expires_at"] + 1):
            recovered = self.engine.advance(unknown["id"], unknown["revision"])
        self.assertEqual(recovered["stage"], "usdc_dispatched")
        self.assertEqual(recovered["events"][-1]["method"], "GET")
        with self.assertRaises(DemoError):
            self.engine.advance(unknown["id"], unknown["revision"])
        final = self.finish(recovered)
        self.assertEqual(final["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(final["settlement"]["provider_payout_count"], 1)
        self.assertEqual(self.ledger_kinds(final).count("provider_dispatch"), 1)
        self.assert_demo_value_conserved(final)

    def test_paid_dispatch_recovers_after_expiry_without_releasing_or_paying_again(self):
        for expiry in ("grant", "quote"):
            with self.subTest(expiry=expiry):
                signed = self.to_step(self.create(), 4)
                submit = self.engine.provider.submit

                def payout_then_interrupt(intent, original_submit=submit):
                    original_submit(intent)
                    self.engine.provider.convert(intent["operation_id"])
                    self.engine.provider.complete(intent["operation_id"])
                    raise RuntimeError("lost complete provider result")

                with patch.object(self.engine.provider, "submit", side_effect=payout_then_interrupt):
                    with self.assertRaises(RuntimeError):
                        self.engine.advance(signed["id"], signed["revision"])
                self.restart()
                unknown = self.engine.get(signed["id"])
                expires = signed["grant"]["expires_at"] if expiry == "grant" else signed["fx_quote"]["expires_at"]
                with patch("purchase_simulator.engine.time.time", return_value=expires + 1):
                    recovered = self.engine.advance(unknown["id"], unknown["revision"])
                self.assertEqual(recovered["stage"], "payout_reconciled")
                self.assertEqual(recovered["buyer"]["available_usdc_units"], CUSTOMER_START - ORDER_COST)
                self.assertEqual(recovered["settlement"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
                final = self.finish(recovered)
                self.assertEqual(final["settlement"]["provider_attempt_count"], 1)
                self.assertEqual(final["settlement"]["provider_payout_count"], 1)
                self.assertNotIn("expired_hold_released", self.ledger_kinds(final))
                self.assert_demo_value_conserved(final)

    def test_crash_while_saving_dispatch_response_preserves_uncertainty(self):
        signed = self.to_step(self.create(), 4)
        enrich = self.engine._enrich_latest_event

        def interrupt_final_save(db, state, **kwargs):
            if state["stage"] == "usdc_dispatched":
                raise RuntimeError("interrupted before application response commit")
            return enrich(db, state, **kwargs)

        with patch.object(self.engine, "_enrich_latest_event", side_effect=interrupt_final_save):
            with self.assertRaises(RuntimeError):
                self.engine.advance(signed["id"], signed["revision"])
        self.restart()
        unknown = self.engine.get(signed["id"])
        self.assertEqual(unknown["stage"], "dispatch_unknown")
        self.assertEqual(unknown["buyer"]["held_usdc_units"], ORDER_COST)
        self.assertEqual(self.ledger_kinds(unknown), ["order_hold"])
        with patch.object(self.engine.provider, "submit") as submit:
            recovered = self.engine.advance(unknown["id"], unknown["revision"])
            submit.assert_not_called()
        final = self.finish(recovered)
        self.assertEqual(final["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(final["settlement"]["provider_payout_count"], 1)
        self.assert_demo_value_conserved(final)

    def test_legacy_unjournaled_provider_acceptance_cannot_release_expired_hold(self):
        signed = self.to_step(self.create(), 4)
        # An old-version interrupted run has no durable dispatch marker, but
        # the independently committed provider record still blocks a release.
        self.engine.provider.submit(signed["intent"])
        with patch("purchase_simulator.engine.time.time", return_value=signed["grant"]["expires_at"] + 1):
            with self.assertRaisesRegex(DemoError, "Dispatch may already exist"):
                self.engine.advance(signed["id"], signed["revision"])
        current = self.engine.get(signed["id"])
        self.assertEqual(current["buyer"]["held_usdc_units"], ORDER_COST)
        self.assertEqual(current["buyer"]["available_usdc_units"], CUSTOMER_START - ORDER_COST)
        self.assertEqual(current["settlement"]["provider_attempt_count"], 1)

    def test_dispatch_without_acceptance_evidence_keeps_hold_after_expiry_and_cancellation(self):
        signed = self.to_step(self.create(), 4)
        with patch.object(self.engine.provider, "submit", side_effect=OSError("connection failed before any reply")) as submit:
            with self.assertRaises(DemoError) as failed:
                self.engine.advance(signed["id"], signed["revision"])
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(failed.exception.current["stage"], "dispatch_unknown")
        self.restart()
        unknown = self.engine.get(signed["id"])
        self.rewrite_saved_state(unknown, lambda raw: raw.__setitem__("scenario", "cancel_before_dispatch"))
        for _ in range(2):
            with patch("purchase_simulator.engine.time.time", return_value=signed["grant"]["expires_at"] + 1):
                with patch.object(self.engine.provider, "submit") as submit:
                    with self.assertRaisesRegex(DemoError, "remain reserved"):
                        self.engine.advance(unknown["id"], unknown["revision"])
                    submit.assert_not_called()
        current = self.engine.get(unknown["id"])
        self.assertEqual(current["revision"], unknown["revision"])
        self.assertEqual(current["buyer"]["available_usdc_units"], CUSTOMER_START - ORDER_COST)
        self.assertEqual(current["buyer"]["held_usdc_units"], ORDER_COST)
        self.assertEqual(current["protection"]["committed_usdc_units"], COMBINED_COVER)
        self.assertEqual(self.ledger_kinds(current), ["order_hold"])
        self.assert_demo_value_conserved(current)

    def test_unavailable_or_changed_dispatch_evidence_never_releases_hold(self):
        signed = self.to_step(self.create(), 4)
        submit = self.engine.provider.submit

        def interrupted(intent):
            submit(intent)
            raise RuntimeError("interrupted")

        with patch.object(self.engine.provider, "submit", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.engine.advance(signed["id"], signed["revision"])
        unknown = self.engine.get(signed["id"])
        with patch.object(self.engine.provider, "lookup", side_effect=OSError("provider offline")):
            with self.assertRaises(DemoError):
                self.engine.advance(unknown["id"], unknown["revision"])
            snapshot = self.engine.get(unknown["id"])
            self.assertIsNotNone(snapshot["provider_read_error"])
            self.assertEqual(snapshot["buyer"]["held_usdc_units"], ORDER_COST)
        self.rewrite_saved_state(unknown, lambda raw: raw["intent"].__setitem__("beneficiary_id", "changed_merchant"))
        with self.assertRaisesRegex(DemoError, "exact intent"):
            self.engine.advance(unknown["id"], unknown["revision"])
        self.assertEqual(self.engine.get(unknown["id"])["buyer"]["held_usdc_units"], ORDER_COST)

    def test_cancel_and_expiry_still_stop_new_dispatch_before_provider_contact(self):
        for scenario in ("success", "cancel_before_dispatch"):
            signed = self.to_step(self.create(scenario), 4)
            with patch.object(self.engine.provider, "submit") as submit:
                if scenario == "success":
                    with patch("purchase_simulator.engine.time.time", return_value=signed["grant"]["expires_at"] + 1):
                        stopped = self.engine.advance(signed["id"], signed["revision"])
                else:
                    stopped = self.engine.advance(signed["id"], signed["revision"])
                submit.assert_not_called()
            self.assertTrue(stopped["terminal"])
            self.assertEqual(stopped["buyer"]["available_usdc_units"], CUSTOMER_START)
            self.assertIsNone(stopped["dispatch_record"])

    def test_mismatched_provider_payout_fails_closed_before_app_settlement(self):
        mutations = (
            ("beneficiary_id", "merchant_attacker_demo"),
            ("source_usdc_units", ORDER_COST + 1),
            ("net_usd_cents", ORDER_USD_CENTS - 1),
        )
        statements = {
            "beneficiary_id": "UPDATE payouts_v3 SET beneficiary_id=? WHERE operation_id=?",
            "source_usdc_units": "UPDATE payouts_v3 SET source_usdc_units=? WHERE operation_id=?",
            "net_usd_cents": "UPDATE payouts_v3 SET net_usd_cents=? WHERE operation_id=?",
        }
        for column, value in mutations:
            with self.subTest(column=column):
                ready = self.to_step(self.create(), 7)
                with closing(sqlite3.connect(self.engine.provider_path)) as db, db:
                    db.execute(statements[column], (value, ready["operation_id"]))

                with self.assertRaises(DemoError) as stopped:
                    self.engine.advance(ready["id"], ready["revision"])
                self.assertEqual(stopped.exception.status, 409)
                current = self.engine.get(ready["id"])
                self.assertEqual(current["step"], 7)
                self.assertEqual(current["settlement"]["merchant_received_usd_cents"], 0)
                self.assertEqual(
                    current["settlement"]["provider_in_transit_usdc_units"], ORDER_COST
                )
                self.assertIsNone(current["settlement_record"])

    def test_non_delivery_uses_reserve_while_merchant_remains_paid(self):
        claim_open = self.to_step(self.create("non_delivery_paid"), 11)
        self.assertEqual(claim_open["delivery_state"], "not_delivered")
        self.assertEqual(claim_open["settlement"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(claim_open["protection"]["reserve_cash_usdc_units"], RESERVE_START)
        self.assertEqual(claim_open["protection"]["committed_usdc_units"], COMBINED_COVER)
        self.assertEqual(claim_open["protection"]["available_usdc_units"], 700 * USDC)

        approved = self.engine.advance(claim_open["id"], claim_open["revision"])
        self.assertEqual(approved["stage"], "claim_approved")
        self.assertEqual(approved["protection"]["reserve_cash_usdc_units"], RESERVE_START)
        self.assertEqual(approved["protection"]["committed_usdc_units"], 100 * USDC)
        self.assertEqual(approved["protection"]["pending_usdc_units"], ORDER_COST)
        self.assertEqual(approved["protection"]["available_usdc_units"], 700 * USDC)

        final = self.finish(approved)
        self.assertEqual(final["stage"], "customer_restored")
        self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
        self.assertEqual(final["settlement"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(final["settlement"]["provider_observed_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(final["protection"]["reserve_cash_usdc_units"], 800 * USDC)
        self.assertEqual(final["protection"]["committed_usdc_units"], 0)
        self.assertEqual(final["protection"]["pending_usdc_units"], 0)
        self.assertEqual(final["protection"]["paid_usdc_units"], ORDER_COST)
        self.assertEqual(final["protection"]["available_usdc_units"], 800 * USDC)
        self.assertEqual(final["recovery_state"], "supplier_recovery_open")
        self.assertEqual(len(final["claims"]), 1)
        claim = final["claims"][0]
        self.assertEqual(claim["loss_type"], "supplier_non_delivery")
        self.assertEqual(claim["status"], "paid")
        self.assertEqual(claim["approved_units"], ORDER_COST)
        self.assertEqual(claim["paid_units"], ORDER_COST)
        self.assertEqual(self.ledger_kinds(final).count("protection_payout"), 1)
        self.assertEqual(final["receipt"]["outcome"]["remedy_usdc_units"], ORDER_COST)

    def test_claim_payout_uses_persisted_approval_when_run_state_is_tampered(self):
        approved = self.to_step(self.create("non_delivery_paid"), 12)
        with closing(sqlite3.connect(self.engine.path)) as db, db:
            raw = json.loads(
                db.execute(
                    "SELECT state_json FROM runs WHERE id=?", (approved["id"],)
                ).fetchone()[0]
            )
            raw["claim_amount_usdc_units"] = CUSTOMER_START
            db.execute(
                "UPDATE runs SET state_json=? WHERE id=?",
                (json.dumps(raw, sort_keys=True, separators=(",", ":")), approved["id"]),
            )

        final = self.engine.advance(approved["id"], approved["revision"])
        self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
        self.assertEqual(final["protection"]["reserve_cash_usdc_units"], 800 * USDC)
        self.assertEqual(final["claims"][0]["approved_units"], ORDER_COST)
        self.assertEqual(final["claims"][0]["paid_units"], ORDER_COST)
        self.assertEqual(final["receipt"]["outcome"]["remedy_usdc_units"], ORDER_COST)

    def test_claim_approval_uses_persisted_request_when_run_state_is_tampered(self):
        claim_open = self.to_step(self.create("non_delivery_paid"), 11)
        with closing(sqlite3.connect(self.engine.path)) as db, db:
            raw = json.loads(
                db.execute(
                    "SELECT state_json FROM runs WHERE id=?", (claim_open["id"],)
                ).fetchone()[0]
            )
            raw["claim_amount_usdc_units"] = CUSTOMER_START
            db.execute(
                "UPDATE runs SET state_json=? WHERE id=?",
                (json.dumps(raw, sort_keys=True, separators=(",", ":")), claim_open["id"]),
            )

        approved = self.engine.advance(claim_open["id"], claim_open["revision"])
        self.assertEqual(approved["claims"][0]["requested_units"], ORDER_COST)
        self.assertEqual(approved["claims"][0]["approved_units"], ORDER_COST)
        self.assertEqual(approved["protection"]["pending_usdc_units"], ORDER_COST)
        final = self.finish(approved)
        self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
        self.assertEqual(final["receipt"]["outcome"]["remedy_usdc_units"], ORDER_COST)

    def test_historical_fixture_pays_only_contractual_extra_ticket_remedy(self):
        loaded = self.create("historical_agent_error")
        self.assertEqual(loaded["entry_mode"], "injected_historical_fixture")
        self.assertEqual(loaded["stage"], "historical_fixture_loaded")
        self.assertEqual(loaded["grant"]["quantity"], 2)
        self.assertEqual(loaded["offer"]["quantity"], 3)
        self.assertEqual(loaded["buyer"]["available_usdc_units"], 0)
        self.assertEqual(loaded["settlement"]["merchant_received_usd_cents"], 30_000)
        self.assertEqual(loaded["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(loaded["protection"]["committed_usdc_units"], COMBINED_COVER)
        self.assertIn("live policy guard was not bypassed", loaded["outcome"]["detail"])

        final = self.finish(loaded)
        self.assertEqual(final["stage"], "complete")
        self.assertEqual(final["buyer"]["available_usdc_units"], 100 * USDC)
        self.assertEqual(final["settlement"]["merchant_received_usd_cents"], 30_000)
        self.assertEqual(final["protection"]["reserve_cash_usdc_units"], 900 * USDC)
        self.assertEqual(final["protection"]["paid_usdc_units"], 100 * USDC)
        self.assertEqual(final["recovery_state"], "belay_agent_error_absorbed")
        self.assertEqual(len(final["claims"]), 1)
        self.assertEqual(final["claims"][0]["loss_type"], "agent_quantity_error")
        self.assertEqual(final["claims"][0]["paid_units"], 100 * USDC)
        self.assertEqual(final["receipt"]["instruction"]["quantity"], 2)
        self.assertEqual(final["receipt"]["purchase"]["quantity"], 3)
        self.assertEqual(final["receipt"]["outcome"]["remedy_usdc_units"], 100 * USDC)
        self.assertEqual(self.ledger_kinds(final).count("protection_payout"), 1)

    def test_cancel_before_dispatch_returns_hold_and_releases_cover(self):
        final = self.finish(self.create("cancel_before_dispatch"))

        self.assertEqual(final["stage"], "cancelled")
        self.assertEqual(final["step"], 5)
        self.assertEqual(final["funding_state"], "returned_before_dispatch")
        self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
        self.assertEqual(final["buyer"]["held_usdc_units"], 0)
        self.assertEqual(final["settlement"]["provider_in_transit_usdc_units"], 0)
        self.assertEqual(final["settlement"]["merchant_received_usd_cents"], 0)
        self.assertEqual(final["settlement"]["provider_attempt_count"], 0)
        self.assertEqual(final["protection"]["committed_usdc_units"], 0)
        self.assertEqual(final["protection"]["reserve_cash_usdc_units"], RESERVE_START)
        self.assertEqual(final["protection"]["available_usdc_units"], RESERVE_START)
        self.assertEqual(self.ledger_kinds(final), ["order_hold", "hold_released"])

    def test_expired_grant_stops_each_pre_dispatch_gate_and_returns_any_hold(self):
        for gate_step in (3, 4, 5):
            with self.subTest(gate_step=gate_step):
                state = self.to_step(self.create(), gate_step - 1)
                with patch(
                    "purchase_simulator.engine.time.time",
                    return_value=state["grant"]["expires_at"] + 1,
                ):
                    final = self.engine.advance(state["id"], state["revision"])

                self.assertTrue(final["terminal"])
                self.assertEqual(final["stage"], "grant_expired")
                self.assertEqual(final["step"], gate_step)
                self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
                self.assertEqual(final["buyer"]["held_usdc_units"], 0)
                self.assertEqual(final["settlement"]["provider_in_transit_usdc_units"], 0)
                self.assertEqual(final["settlement"]["merchant_received_usd_cents"], 0)
                self.assertEqual(final["settlement"]["provider_attempt_count"], 0)
                self.assertEqual(final["protection"]["committed_usdc_units"], 0)
                self.assertEqual(final["protection"]["reserve_cash_usdc_units"], RESERVE_START)
                self.assertNotIn("provider_dispatch", self.ledger_kinds(final))

    def test_expired_fx_quote_is_rejected_at_every_admission_or_dispatch_gate(self):
        for gate_step in (3, 4, 5):
            with self.subTest(gate_step=gate_step):
                state = self.to_step(self.create(), gate_step - 1)
                quote_expiry = state["fx_quote"]["expires_at"]
                with patch(
                    "purchase_simulator.engine.time.time", return_value=quote_expiry + 1
                ):
                    final = self.engine.advance(state["id"], state["revision"])

                self.assertTrue(final["terminal"])
                self.assertEqual(
                    final["stage"], "policy_blocked" if gate_step == 3 else "terms_rejected"
                )
                self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
                self.assertEqual(final["buyer"]["held_usdc_units"], 0)
                self.assertEqual(final["settlement"]["provider_in_transit_usdc_units"], 0)
                self.assertEqual(final["settlement"]["merchant_received_usd_cents"], 0)
                self.assertEqual(final["settlement"]["provider_attempt_count"], 0)
                self.assertEqual(final["protection"]["committed_usdc_units"], 0)
                self.assertNotIn("provider_dispatch", self.ledger_kinds(final))
                failed = {
                    check["name"]
                    for check in final["policy_decision"]["checks"]
                    if not check["passed"]
                }
                self.assertIn("quote_expiry", failed)

    def test_admitted_hold_cannot_be_reused_for_changed_valid_terms(self):
        for gate_step in (4, 5):
            with self.subTest(gate_step=gate_step):
                state = self.to_step(self.create(), gate_step - 1)

                def change_price(raw):
                    raw["offer"]["unit_price_usd_cents"] = 9_000
                    raw["offer"]["total_usd_cents"] = 18_000
                    raw["fx_quote"]["source_usdc_units"] = 180 * USDC
                    raw["fx_quote"]["merchant_net_usd_cents"] = 18_000

                self.rewrite_saved_state(state, change_price)
                final = self.engine.advance(state["id"], state["revision"])
                self.assertEqual(final["stage"], "terms_rejected")
                self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
                self.assertEqual(final["buyer"]["held_usdc_units"], 0)
                self.assertEqual(final["settlement"]["merchant_received_usd_cents"], 0)
                self.assertEqual(final["settlement"]["provider_attempt_count"], 0)
                failed = {
                    check["name"]
                    for check in final["policy_decision"]["checks"]
                    if not check["passed"]
                }
                self.assertIn("admitted_transaction_binding", failed)

    def test_signed_intent_cannot_be_changed_before_dispatch(self):
        signed = self.to_step(self.create(), 4)

        def change_beneficiary(raw):
            raw["intent"]["beneficiary_id"] = "merchant_attacker_demo"

        self.rewrite_saved_state(signed, change_beneficiary)
        final = self.engine.advance(signed["id"], signed["revision"])
        self.assertEqual(final["stage"], "terms_rejected")
        self.assertEqual(final["buyer"]["available_usdc_units"], CUSTOMER_START)
        self.assertEqual(final["buyer"]["held_usdc_units"], 0)
        self.assertEqual(final["settlement"]["merchant_received_usd_cents"], 0)
        self.assertEqual(final["settlement"]["provider_attempt_count"], 0)
        failed = {
            check["name"]
            for check in final["policy_decision"]["checks"]
            if not check["passed"]
        }
        self.assertIn("exact_signed_intent", failed)

    def test_evidence_conflict_abstains_without_reserve_payment(self):
        final = self.finish(self.create("evidence_conflict"))

        self.assertEqual(final["stage"], "review_required")
        self.assertTrue(final["manual_review"])
        self.assertEqual(final["delivery_state"], "evidence_conflict")
        self.assertEqual(final["recovery_state"], "manual_review")
        self.assertEqual(final["settlement"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(final["buyer"]["available_usdc_units"], 100 * USDC)
        self.assertEqual(final["protection"]["reserve_cash_usdc_units"], RESERVE_START)
        self.assertEqual(final["protection"]["committed_usdc_units"], COMBINED_COVER)
        self.assertEqual(final["protection"]["paid_usdc_units"], 0)
        self.assertEqual(final["protection"]["available_usdc_units"], 700 * USDC)
        self.assertEqual(len(final["claims"]), 1)
        self.assertEqual(final["claims"][0]["loss_type"], "ambiguous_delivery")
        self.assertEqual(final["claims"][0]["status"], "open")
        self.assertEqual(final["claims"][0]["paid_units"], 0)
        self.assertNotIn("protection_payout", self.ledger_kinds(final))

    def test_stale_revision_returns_current_state_without_mutation(self):
        initial = self.create()
        advanced = self.engine.advance(initial["id"], initial["revision"])
        with self.assertRaises(DemoError) as stopped:
            self.engine.advance(initial["id"], initial["revision"])
        self.assertEqual(stopped.exception.status, 409)
        self.assertEqual(stopped.exception.current["revision"], advanced["revision"])
        current = self.engine.get(initial["id"])
        self.assertEqual(current["revision"], advanced["revision"])
        self.assertEqual(current["events"], advanced["events"])
        self.assertEqual(current["ledger"], advanced["ledger"])

    def test_concurrent_same_revision_advances_once_and_pays_once(self):
        ready = self.to_step(self.create(), 7)
        barrier = threading.Barrier(2)

        def advance():
            barrier.wait(timeout=5)
            try:
                return self.engine.advance(ready["id"], ready["revision"])
            except DemoError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _unused: advance(), range(2)))

        accepted = [value for value in outcomes if isinstance(value, dict)]
        rejected = [value for value in outcomes if isinstance(value, DemoError)]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].status, 409)
        current = self.engine.get(ready["id"])
        self.assertEqual(current["revision"], ready["revision"] + 1)
        self.assertEqual(current["settlement"]["provider_attempt_count"], 1)
        self.assertEqual(current["settlement"]["provider_payout_count"], 1)
        self.assertEqual(current["settlement"]["merchant_received_usd_cents"], ORDER_USD_CENTS)
        self.assertEqual(self.ledger_kinds(current).count("conversion_and_merchant_payout"), 1)


class PurchaseHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="belay-v03-http-test-")
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

    def create(self, scenario="success"):
        status, state = self.request(
            "POST", "/api/runs",
            {"scenario": scenario, "budget_cents": 30_000, "quantity": 2},
        )
        self.assertEqual(status, 201)
        return state

    def test_create_get_and_stale_advance_have_consistent_v03_state(self):
        state = self.create()
        self.assertEqual(state["schema_version"], SCHEMA_VERSION)
        status, loaded = self.request("GET", f"/api/runs/{state['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(loaded["buyer"]["available_usdc_units"], CUSTOMER_START)

        route = f"/api/runs/{state['id']}/advance"
        status, advanced = self.request("POST", route, {"expected_revision": 0})
        self.assertEqual(status, 200)
        status, conflict = self.request("POST", route, {"expected_revision": 0})
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current"]["revision"], advanced["revision"])
        self.assertEqual(conflict["current"]["id"], state["id"])

    def test_http_rejects_malformed_bodies_unknown_fields_and_invalid_inputs(self):
        for raw in (b"{", b"[]", b"null", b'"text"'):
            with self.subTest(raw=raw):
                status, result = self.request("POST", "/api/runs", raw=raw)
                self.assertEqual(status, 400)
                self.assertIn("error", result)

        for override in (
            {"scenario": "unknown"}, {"scenario": []}, {"budget_cents": True},
            {"budget_cents": 19_999}, {"budget_cents": 30_000.5},
            {"quantity": 3}, {"quantity": True}, {"extra": "untrusted"},
        ):
            with self.subTest(override=override):
                body = {"scenario": "success", "budget_cents": 30_000, "quantity": 2, **override}
                status, result = self.request("POST", "/api/runs", body)
                self.assertEqual(status, 400)
                self.assertIn("error", result)

        state = self.create()
        route = f"/api/runs/{state['id']}/advance"
        for body in ({}, {"expected_revision": True}, {"expected_revision": -1},
                     {"expected_revision": 0, "extra": "untrusted"}):
            with self.subTest(body=body):
                status, result = self.request("POST", route, body)
                self.assertEqual(status, 400)
                self.assertIn("error", result)
        self.assertEqual(self.engine.get(state["id"])["revision"], 0)

    def test_http_rejects_cross_origin_non_json_and_unsupported_routes(self):
        state = self.create()
        route = f"/api/runs/{state['id']}/advance"
        for headers in (
            {"Origin": "https://untrusted.example"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            with self.subTest(headers=headers):
                # The server rejects these headers before reading a body. Keep
                # this request bodyless so Windows does not reset a socket that
                # still contains deliberately unread request bytes.
                status, _result = self.request("POST", route, raw=b"", headers=headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.engine.get(state["id"])["revision"], 0)

        status, _result = self.request(
            "POST", "/api/runs", raw=b"", headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)
        status, _result = self.request("GET", "/api/config", headers={"Host": "untrusted.example"})
        self.assertEqual(status, 403)
        status, _result = self.request("GET", "/api/not-a-route")
        self.assertEqual(status, 404)
        status, _result = self.request("PUT", f"/api/runs/{state['id']}")
        self.assertEqual(status, 405)


if __name__ == "__main__":
    unittest.main(verbosity=2)
