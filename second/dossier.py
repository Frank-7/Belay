"""The adjudicator's output schema, and the agent's raw claim.

Two types here and the distinction between them is the trust boundary.

`Claim` is what the agent said. Untrusted. It carries a verdict, a list of
citation digests, and prose. Note what it *cannot* carry: no anchor, no
amount, no scope, no external id. The agent is not permitted to name an
effect identity or a sum of money, for the same reason `anchored.py` does
not let the model invent an anchor. Divergence in prose is harmless;
divergence in an identity is the bug this repo is about.

`Dossier` is what survived validation. Its `amount_cents` and its proposal
scope are filled in from the journal intent by `adjudicate.py`, never from
the agent.

The proposal is typed, and this is inherited scar tissue rather than
tidiness. FINDINGS.md S6 records a bug we shipped: `resolve_ambiguous_refund`
collapsed "ask the service what happened" and "issue the effect because it
never landed" into one step, which is safe against duplication and unsafe
against authorisation -- if the original call never landed, the "retry" is
the first and only call, performed with no live permission. The harness
caught it at a 50% rate. An adjudicator is the same shape of hazard with a
model in the loop, so the two rungs are separate members of an enum here and
`requires_authz` is derived from the kind rather than set by a caller.

  QUERY       reports what out-of-band records already show. Creates
              nothing. Needs no permission. Always safe to apply.
  COMPLETION  issues the effect because the evidence proved it never
              landed. A new external effect. Needs a live permission check
              at the instant of execution, exactly as a first attempt would
              (CONTRACT.md I2).

ABSTAIN is a first-class outcome, not a failure. I3 already says halting is
acceptable, so an adjudicator that abstains and stays silent has cost
nothing beyond the halt that was already there. That asymmetry is the
governing design rule of this package: a wrong resolution is strictly worse
than no resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    COMMITTED = "committed"   # out-of-band records show the effect landed
    ABSENT = "absent"         # a source complete over the window is silent
    ABSTAIN = "abstain"       # not established; the anchor stays halted


class ProposalKind(str, Enum):
    NONE = "none"             # abstained; nothing to do
    QUERY = "query"           # creates nothing, needs no permission
    COMPLETION = "completion" # new external effect, needs live authz


@dataclass
class Claim:
    """Raw, untrusted agent output. Validated in `adjudicate.py`."""

    verdict: str
    citations: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "citations": list(self.citations),
            "reasoning": list(self.reasoning),
        }


@dataclass
class Proposal:
    kind: ProposalKind
    scope: str | None = None
    amount_cents: int | None = None

    @property
    def requires_authz(self) -> bool:
        """Derived, never assigned. A completion needs a live scope check;
        a query never does."""
        return self.kind is ProposalKind.COMPLETION

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "scope": self.scope,
            "amount_cents": self.amount_cents,
            "requires_authz": self.requires_authz,
        }


@dataclass
class Dossier:
    """A validated adjudication of one anchored slot."""

    anchor: str
    slot: str
    verdict: Verdict
    proposal: Proposal
    amount_cents: int | None = None
    external_id: int | None = None
    citations: list[dict] = field(default_factory=list)   # observation dicts
    reasoning: list[str] = field(default_factory=list)    # the agent's prose
    validator_notes: list[str] = field(default_factory=list)
    pointers_proposed: int = 0
    pointers_resolved: int = 0

    @property
    def resolved(self) -> bool:
        return self.verdict is not Verdict.ABSTAIN

    def as_dict(self) -> dict:
        return {
            "anchor": self.anchor,
            "slot": self.slot,
            "verdict": self.verdict.value,
            "proposal": self.proposal.as_dict(),
            "amount_cents": self.amount_cents,
            "external_id": self.external_id,
            "citations": list(self.citations),
            "reasoning": list(self.reasoning),
            "validator_notes": list(self.validator_notes),
            "pointers_proposed": self.pointers_proposed,
            "pointers_resolved": self.pointers_resolved,
        }

    @classmethod
    def abstain(
        cls,
        anchor: str,
        slot: str,
        why: str,
        *,
        reasoning: list[str] | None = None,
        citations: list[dict] | None = None,
        pointers_proposed: int = 0,
        pointers_resolved: int = 0,
    ) -> Dossier:
        """The default outcome. Every validation failure routes here."""
        return cls(
            anchor=anchor,
            slot=slot,
            verdict=Verdict.ABSTAIN,
            proposal=Proposal(ProposalKind.NONE),
            citations=list(citations or []),
            reasoning=list(reasoning or []),
            validator_notes=[why],
            pointers_proposed=pointers_proposed,
            pointers_resolved=pointers_resolved,
        )
