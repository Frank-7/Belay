"""Adapt saved payment authority and fictional provider records to Recovery Desk.

The adapter performs lookup only. It cannot dispatch, sign, credit or release funds.
Old provider records without captured intent remain unresolved rather than acquiring
new authority from a currently displayed plan.
"""

import json

from purchase_simulator.mission_control import (
    _grant_self_integrity_matches,
    _signed_intent_matches,
)
from recovery_app.payment import PaymentIntent, blocked_finding, canonical
from recovery_app.payment import investigate as investigate_evidence


def intent_from_state(state):
    if not _grant_self_integrity_matches(state) or not _signed_intent_matches(state):
        raise ValueError("The saved authority or signed instruction changed")
    grant = state["grant"]
    if (grant["mission_id"] != state["id"]
            or grant["operation_id"] != state["operation_id"]
            or grant["request_digest"] != state["request_digest"]):
        raise ValueError("The saved authority belongs to another payment")
    raw = {key: value for key, value in state["signed_intent"].items()
           if key not in {"digest", "signature"}}
    return PaymentIntent(
        run_id=state["id"], revision=state["revision"], mission_id=state["id"],
        operation_id=raw["operation_id"], grant_digest=raw["grant_digest"],
        beneficiary_id=raw["payee_id"], source_usdc_units=raw["source_usdc_units"],
        net_usd_cents=raw["destination_usd_cents"], intent_json=canonical(raw),
    )


def investigate(state, lookup):
    try:
        intent = intent_from_state(state)
    except (KeyError, ValueError, TypeError, OverflowError, RecursionError):
        return blocked_finding(state.get("id"), state.get("revision"),
                               "Saved payment authority is incomplete or inconsistent. Keep the original payment unresolved.")
    try:
        record = lookup(intent.operation_id)
        if record is None:
            return investigate_evidence(intent, None)
        # Every field is from a saved provider/dispatch record, never filled from
        # the current expected intent to turn absent evidence into a match.
        raw_intent = record.get("intent_json")
        if raw_intent is None or record.get("grant_json") is None:
            finding = investigate_evidence(intent, None)
            finding["summary"] = (
                "This older provider record lacks captured dispatch authority. "
                "Keep it unresolved for manual review."
            )
            return finding
        observation = {
            "operation_id": record.get("operation_id"),
            "mission_id": record.get("mission_id"),
            "intent_json": raw_intent,
            "beneficiary_id": record.get("payee_id"),
            "source_usdc_units": record.get("source_usdc_units"),
            "net_usd_cents": record.get("amount_usd_cents"),
            "provider_reference": record.get("provider_reference"),
            "funding_state": "settled" if record.get("status") == "paid" else "processing",
            "conversion_state": "converted" if record.get("status") == "paid" else "pending",
            "payout_state": record.get("status"),
            "source_asset": record.get("source_asset"),
            "destination_asset": record.get("destination_asset"),
            "attempt_count": record.get("attempt_count"),
            "grant_json": record.get("grant_json"),
        }
        finding = investigate_evidence(intent, observation)
        linkage = (
            record.get("mission_id") == state["id"]
            and record.get("source_asset") == "USDC"
            and record.get("destination_asset") == "USD"
            and type(record.get("attempt_count")) is int and record["attempt_count"] == 1
            and record.get("grant_json") == canonical(state["grant"])
            and state["money"]["provider_in_transit_usdc_units"] == intent.source_usdc_units
            and state["money"]["payment_hold_usdc_units"] == 0
            and state["money"]["payee_received_usd_cents"] == 0
        )
        finding["checks"].append({"label": "Original dispatch authority, assets and reserved funds", "passed": linkage})
        if not linkage:
            finding.update(verdict="conflict", can_reconcile=False, citations=[],
                           summary="The original dispatch authority or accounting does not match. Reconciliation is blocked.")
        # Parse the captured instruction only to reject corrupt evidence. The
        # shared investigator already compares its exact canonical bytes.
        if raw_intent is not None:
            json.loads(raw_intent)
        return finding
    except Exception:
        return investigate_evidence(intent, None, unavailable=True)
