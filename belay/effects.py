"""Typed effects and the cooperation a service offers for reconciliation.

The central idea of the repo: an effect is not just a function call. It is
a declaration of (a) what scope authorises it, (b) whether the world can be
put back, and (c) what the target service will tell us if we crash mid-call.

(c) is what determines which guarantees are *available*. A runtime cannot
manufacture reconcilability that the service does not offer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Tier(str, Enum):
    """What the external service will do for us after an ambiguous call."""

    # Accepts a caller-supplied idempotency key and dedupes on it.
    # A retry with the same key is safe and returns the original outcome.
    IDEMPOTENT = "idempotent"

    # No dedupe, but we can ask "did you ever see reference R?" after the fact.
    # A retry would double-commit, so we must query before retrying.
    QUERYABLE = "queryable"

    # No dedupe, no lookup. An ambiguous call is permanently ambiguous.
    OPAQUE = "opaque"


class Reversibility(str, Enum):
    COMPENSABLE = "compensable"      # a later action can undo it
    IRREVERSIBLE = "irreversible"    # money has left; nothing undoes it


@dataclass(frozen=True)
class EffectSpec:
    name: str
    scope: str                  # the permission required at execution time
    reversibility: Reversibility

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.name}[{self.scope}]"


# The two effects in the refund workflow.
REFUND = EffectSpec(
    name="payments.refund",
    scope="payments:refund",
    reversibility=Reversibility.IRREVERSIBLE,
)

CREDIT = EffectSpec(
    name="credits.issue",
    scope="credits:issue",
    reversibility=Reversibility.COMPENSABLE,
)

EFFECTS = {e.name: e for e in (REFUND, CREDIT)}
