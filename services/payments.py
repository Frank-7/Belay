"""Three payment services that differ only in what they offer after a crash.

A mock that always behaves well cannot substantiate a recovery claim, so
each tier here implements its semantics honestly, including the ones that
make recovery impossible.

Every tier calls `chaos.maybe_crash("in_flight")` *after* committing to the
ledger and *before* returning. That is the window the whole repo is about:
the effect exists, the caller has no idea.
"""

from __future__ import annotations

from dataclasses import dataclass

from belay import chaos
from belay.effects import Tier
from services.ledger import Ledger


@dataclass
class Receipt:
    external_id: int
    amount_cents: int
    deduped: bool = False


class NoSuchCapability(Exception):
    pass


class _Base:
    name = "payments"
    tier: Tier

    def __init__(self, ledger: Ledger):
        self.ledger = ledger


class IdempotentPayments(_Base):
    """Tier 1. Accepts a caller key and dedupes on it. Retry is safe."""

    tier = Tier.IDEMPOTENT

    def refund(self, order_id: str, amount_cents: int, idem_key: str) -> Receipt:
        existing = self.ledger.by_idem(self.name, idem_key)
        if existing is not None:
            return Receipt(int(existing["id"]), int(existing["amount_cents"]), deduped=True)
        rid = self.ledger.commit_effect(
            self.name, "refund", order_id, amount_cents, idem_key=idem_key
        )
        chaos.maybe_crash("in_flight")
        return Receipt(rid, amount_cents)

    def lookup(self, idem_key: str) -> Receipt | None:
        row = self.ledger.by_idem(self.name, idem_key)
        if row is None:
            return None
        return Receipt(int(row["id"]), int(row["amount_cents"]), deduped=True)


class QueryablePayments(_Base):
    """Tier 2. No dedupe, so a blind retry double-charges. But we can ask
    afterwards whether a given client reference was ever seen, which makes
    the ambiguity resolvable by one extra round trip."""

    tier = Tier.QUERYABLE

    def refund(self, order_id: str, amount_cents: int, client_ref: str) -> Receipt:
        rid = self.ledger.commit_effect(
            self.name, "refund", order_id, amount_cents, client_ref=client_ref
        )
        chaos.maybe_crash("in_flight")
        return Receipt(rid, amount_cents)

    def lookup(self, client_ref: str) -> Receipt | None:
        row = self.ledger.by_client_ref(self.name, client_ref)
        if row is None:
            return None
        return Receipt(int(row["id"]), int(row["amount_cents"]))


class OpaquePayments(_Base):
    """Tier 3. Fire and hope. No dedupe, no lookup, no reconciliation.

    This tier is not a strawman. Card processors with no idempotency
    support, partner APIs behind a queue, and most internal RPC endpoints
    written before anyone thought about retries all behave this way.
    """

    tier = Tier.OPAQUE

    def refund(self, order_id: str, amount_cents: int) -> Receipt:
        rid = self.ledger.commit_effect(self.name, "refund", order_id, amount_cents)
        chaos.maybe_crash("in_flight")
        return Receipt(rid, amount_cents)

    def lookup(self, *_args, **_kwargs):
        raise NoSuchCapability(
            "opaque tier offers no post-hoc lookup; ambiguity is permanent"
        )


class CreditService(_Base):
    """Second effect in the workflow. Always idempotent, so that the
    interesting failures stay concentrated on the refund."""

    name = "credits"
    tier = Tier.IDEMPOTENT

    def issue(self, order_id: str, amount_cents: int, idem_key: str) -> Receipt:
        existing = self.ledger.by_idem(self.name, idem_key)
        if existing is not None:
            return Receipt(int(existing["id"]), int(existing["amount_cents"]), deduped=True)
        rid = self.ledger.commit_effect(
            self.name, "credit", order_id, amount_cents, idem_key=idem_key
        )
        return Receipt(rid, amount_cents)


TIERS = {
    "idempotent": IdempotentPayments,
    "queryable": QueryablePayments,
    "opaque": OpaquePayments,
}


def build(tier: str, ledger: Ledger) -> _Base:
    return TIERS[tier](ledger)
