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

from recovery_app import payment as payment_evidence

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
    return payment_evidence.blocked_finding(run_id, revision, reason,
                                            schema=SCHEMA, provider="purchase_simulator")


def investigate(intent: PurchaseIntent, provider_record: dict | None, *, unavailable=False):
    return payment_evidence.investigate(intent, provider_record, unavailable=unavailable,
                                        schema=SCHEMA, provider="purchase_simulator", domain="purchase")
