"""Typed, read-only purchase investigation for Recovery Desk.

This domain never projects USDC or USD into a research refund slot. It accepts
an immutable purchase intent and a provider observation, and returns evidence
findings only. No wallet, provider client, ledger or execution callback enters
this module. The purchasing executor must check fresh evidence before acting.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from second.evidence import Observation, Pointer

SCHEMA = "belay.purchase.investigation.v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class PurchaseIntent:
    run_id: str
    revision: int
    mission_id: str
    order_id: str
    operation_id: str
    grant_digest: str
    beneficiary_id: str
    source_usdc_units: int
    net_usd_cents: int
    intent_json: str

    def __post_init__(self):
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("Invalid purchase revision")
        for field in ("run_id", "mission_id", "order_id", "operation_id", "beneficiary_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value):
                raise ValueError("Invalid purchase identity")
        for value in (self.source_usdc_units, self.net_usd_cents):
            if type(value) is not int or not 0 < value <= 2**53 - 1:
                raise ValueError("Use bounded integer currency units")
        if not isinstance(self.grant_digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", self.grant_digest):
            raise ValueError("Invalid mission authority digest")
        if not isinstance(self.intent_json, str) or len(self.intent_json.encode()) > 8192:
            raise ValueError("Invalid purchase intent")
        intent = json.loads(self.intent_json)
        if not isinstance(intent, dict):
            raise ValueError("Purchase intent must be an object")
        if canonical(intent) != self.intent_json:
            raise ValueError("Purchase intent must be canonical")
        expected = {
            "operation_id": self.operation_id, "order_id": self.order_id,
            "grant_digest": self.grant_digest, "beneficiary_id": self.beneficiary_id,
            "source_asset": "USDC", "destination_asset": "USD",
            "source_usdc_units": self.source_usdc_units, "net_usd_cents": self.net_usd_cents,
        }
        if any(canonical(intent.get(key)) != canonical(value) for key, value in expected.items()):
            raise ValueError("Purchase intent fields disagree")

    def view(self):
        result = asdict(self)
        result.pop("intent_json")
        result.update(source_asset="USDC", source_decimals=6,
                      destination_asset="USD", destination_decimals=2,
                      intent_digest="sha256:" + hashlib.sha256(self.intent_json.encode()).hexdigest())
        return result


def blocked_finding(run_id, revision, reason):
    return {
        "schema_version": SCHEMA, "run_id": run_id, "revision": revision,
        "operation_id": None, "intent_digest": None, "evidence_digest": None,
        "verdict": "unknown", "can_reconcile": False, "summary": reason,
        "checks": [], "observations": [], "citations": [], "intent": None,
        "provider": "purchase_simulator", "mode": "deterministic",
        "scope": "Fictional USD payout evidence; no money moved",
    }


def investigate(intent: PurchaseIntent, provider_record: dict | None, *, unavailable=False):
    """Inspect one exact operation; silence never authorizes a replacement."""
    result = blocked_finding(intent.run_id, intent.revision,
                             "The original payout is not confirmed. Keep its outcome unknown.")
    result.update(operation_id=intent.operation_id, intent_digest=intent.view()["intent_digest"],
                  intent=intent.view())
    if unavailable or provider_record is None:
        result["summary"] = ("The provider could not be read. Keep the funds reserved and inspect the original operation."
                             if unavailable else "No provider record was found. A missing record does not authorize another payout.")
        return result
    try:
        if not isinstance(provider_record, dict) or len(canonical(provider_record).encode()) > 16_384:
            raise ValueError("Oversized or invalid provider observation")
        # Snapshot the observation. Neither caller nor an explanation can edit it.
        record = json.loads(canonical(provider_record))
        result["evidence_digest"] = digest(record)
        observation = Observation(
            Pointer("purchase_provider", "operation:" + intent.operation_id),
            {"source": "purchase_provider", "operation": record},
            "fictional-provider:operation:" + intent.operation_id,
        )
        result["observations"] = [{"source": "purchase_provider", **observation.as_dict()}]
        checks = []

        def check(label, passed):
            checks.append({"label": label, "passed": bool(passed)})

        check("Original operation", record.get("operation_id") == intent.operation_id)
        check("Exact saved order, mission and quote", record.get("intent_json") == intent.intent_json)
        check("Bound merchant beneficiary", record.get("beneficiary_id") == intent.beneficiary_id)
        check("USDC amount in six-decimal base units", type(record.get("source_usdc_units")) is int
              and record["source_usdc_units"] == intent.source_usdc_units)
        check("Separate USD amount in cents", type(record.get("net_usd_cents")) is int
              and record["net_usd_cents"] == intent.net_usd_cents)
        reference = record.get("provider_reference")
        check("Provider receipt identity", isinstance(reference, str)
              and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", reference) is not None)
        identity_ok = all(item["passed"] for item in checks)
        check("Funding settled", record.get("funding_state") == "settled")
        check("Conversion confirmed", record.get("conversion_state") == "converted")
        check("USD payout confirmed by the fictional provider", record.get("payout_state") == "paid")
        result["checks"] = checks
        if not identity_ok or (record.get("payout_state") == "paid" and not all(item["passed"] for item in checks)):
            result.update(verdict="conflict", summary="Provider evidence disagrees with the saved purchase. Reconciliation is blocked.")
        elif all(item["passed"] for item in checks):
            result.update(verdict="paid", can_reconcile=True, citations=[observation.digest],
                          summary="The original USD payout is confirmed in the fictional provider. Reconcile it without sending again. Delivery and reimbursement remain separate.")
        else:
            result["summary"] = "Funding or conversion alone does not confirm the USD payout. Keep the original operation unresolved."
    except (ValueError, TypeError, OverflowError, RecursionError):
        result.update(verdict="unknown", can_reconcile=False,
                      summary="The provider observation could not be read safely. No payout is authorized.",
                      observations=[], checks=[], citations=[])
    return result
