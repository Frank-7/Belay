"""The agent that debugs the agent.

Same stance as `belay/agent.py`: this stands in for an LLM call, and the
only properties we need from it are the ones that matter to the
architecture. Here those are the *failure* properties, because the claim
under test is not "the model is good" -- it is "the pipeline is safe when
the model is bad".

So this simulator is parameterised by its vices, and the experiment sweeps
them:

  `hallucination_p`   emits pointers to sources or selectors that do not
                      exist. Should cost wasted fetches and nothing else.
  `overconfidence_p`  asserts a verdict the evidence does not support,
                      including fabricated citation digests. Should be
                      caught by `validate` and forced to abstain.
  `laziness_p`        skips the manifest, asking only "any refunds for this
                      order?". Should degrade to abstention on absence,
                      because silence without coverage proves nothing --
                      never to a false ABSENT.

A *competent* agent is all three at zero, and it is still not trusted: it
goes through the same validator. Nothing in the pipeline distinguishes them.

Swapping in a real model touches these two methods and nothing else. The
prompt would be `view` plus the fetched observations; the response schema is
`list[str]` then `Claim`. Both are deliberately small. The reason to keep
the surface this narrow is that everything crossing it gets verified, and
verification is only cheap while the surface is a pointer and a three-way
enum -- widen it to "and here is the amount" and you are back to trusting a
model with an identity, which is the failure this repo exists to describe.
"""

from __future__ import annotations

import os
import random

from second.dossier import Claim
from second.evidence import SEL_MANIFEST, SEL_ORDER, Observation

NAME = "heuristic"

# Sources a confabulating agent likes to invent. Every one of these is a
# plausible-sounding system that is not in the catalogue, which is exactly
# the shape of a real hallucination: locally coherent, unresolvable.
FICTIONAL = (
    "reconciliation_api",
    "processor_dashboard",
    "audit_log",
    "statement_v2",
)


class DebugAgent:
    """Proposes pointers, then reads verified observations and concludes."""

    def __init__(
        self,
        hallucination_p: float | None = None,
        overconfidence_p: float | None = None,
        laziness_p: float | None = None,
        seed: int | None = None,
    ):
        env = os.environ.get
        self.hallucination_p = (
            hallucination_p if hallucination_p is not None
            else float(env("SECOND_HALLUCINATION_P", "0.0"))
        )
        self.overconfidence_p = (
            overconfidence_p if overconfidence_p is not None
            else float(env("SECOND_OVERCONFIDENCE_P", "0.0"))
        )
        self.laziness_p = (
            laziness_p if laziness_p is not None
            else float(env("SECOND_LAZINESS_P", "0.0"))
        )
        # Seedable so a single adjudication can be demonstrated
        # deterministically; unseeded it draws fresh entropy per process,
        # like the agent under test.
        self._rng = random.Random(seed if seed is not None else os.urandom(16))

    # -- round 1 -----------------------------------------------------------

    def propose_pointers(self, view: dict) -> list[str]:
        """Where to look. Strings; the fetcher is the authority on whether
        any of them mean anything."""
        order_id = view["order_id"]
        pointers: list[str] = []

        for source in view.get("evidence_sources_available", []):
            # Ask what the source covers, then ask it the question. A lazy
            # agent skips the first and cannot establish absence.
            if self._rng.random() >= self.laziness_p:
                pointers.append(f"{source}:{SEL_MANIFEST}")
            pointers.append(f"{source}:{SEL_ORDER}:{order_id}")

            if self._rng.random() < self.hallucination_p:
                # Ask an opaque source about the anchor it never received.
                # Reasonable-looking, unanswerable.
                pointers.append(f"{source}:anchor:{view['anchor']}")

        if self._rng.random() < self.hallucination_p:
            pointers.append(f"{self._rng.choice(FICTIONAL)}:{SEL_ORDER}:{order_id}")
        if self._rng.random() < self.hallucination_p:
            pointers.append("this is not a pointer")

        return pointers

    # -- round 2 -----------------------------------------------------------

    def conclude(self, view: dict, observations: list[Observation]) -> Claim:
        """Read the verified observations and state a verdict.

        The honest path here is short. The interesting part is the two
        dishonest branches below, which exist so the experiment can show
        they are absorbed rather than believed.
        """
        order_id = view["order_id"]
        amount = view["amount_cents"]

        hits = [
            (o, rec)
            for o in observations
            for rec in o.matches
            if rec.get("order_id") == order_id
            and int(rec.get("amount_cents", -1)) == amount
        ]
        if hits:
            obs, _ = hits[0]
            return Claim(
                verdict="committed",
                citations=[obs.digest],
                reasoning=[
                    f"{obs.pointer} holds a {amount}c refund for {order_id}; "
                    "a hit in any out-of-band record is proof the effect landed",
                ],
            )

        # Nothing found. Can any source's silence actually carry weight?
        manifests = {
            o.payload.get("source"): o
            for o in observations
            if o.pointer.kind == SEL_MANIFEST
        }
        silent = {
            o.payload.get("source"): o
            for o in observations
            if o.pointer.kind == SEL_ORDER and not o.matches
        }
        for source, man in manifests.items():
            cov = man.payload.get("coverage") or {}
            if source not in silent:
                continue
            if cov.get("kind") == "complete_until" and (
                cov.get("cutoff_ts") is not None
                and view["intent_ts"] <= cov["cutoff_ts"]
            ):
                return Claim(
                    verdict="absent",
                    citations=[man.digest, silent[source].digest],
                    reasoning=[
                        f"{source} claims completeness through "
                        f"{cov['cutoff_ts']} and the intent is at "
                        f"{view['intent_ts']}, inside that window",
                        f"{source} holds no refund for {order_id}, so the "
                        "effect never landed and the slot can be completed",
                    ],
                )

        # --- the dishonest branches ---
        if self._rng.random() < self.overconfidence_p:
            # Guess absence on uncovered silence. This is the dangerous
            # mistake -- acting on it issues a duplicate refund -- and it is
            # exactly the inference a fluent model will produce, because
            # "I looked and found nothing" reads as evidence.
            return Claim(
                verdict="absent",
                citations=[o.digest for o in observations[:1]],
                reasoning=[
                    "searched the available records and found no refund, so "
                    "it presumably never went through",
                ],
            )
        if self._rng.random() < self.overconfidence_p:
            # Assert commitment citing a digest nobody produced.
            return Claim(
                verdict="committed",
                citations=["0" * 16],
                reasoning=["the refund appears in the processor records"],
            )

        return Claim(
            verdict="abstain",
            citations=[o.digest for o in observations],
            reasoning=[
                "no source available here is both complete over the window "
                "containing the intent and silent, so absence is not "
                "established and a retry could duplicate the refund",
            ],
        )
