"""The agent under test.

Stands in for an LLM call. The only property we need from it is the one
that breaks replay: **two invocations with identical inputs may return
different decisions**, and the decision determines control flow.

We do not use a real model here. A real model would make the experiment
slower, non-reproducible, and no more convincing, because the mechanism
under study is the runtime's response to divergence, not the model's
reasoning. `experiments/run_live_agent.py` shows how to swap in a real
model call, and the measured divergence rate it produces is the parameter
this simulator takes as input.

Each process seeds its own RNG from os.urandom, so a recovering process
draws independently of the process that crashed. That is precisely the
situation a replay-based runtime assumes cannot happen.
"""

from __future__ import annotations

import os
import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Plan:
    """What the agent decided to do. Note that the *number of effects*
    depends on the decision, which is why control flow is at stake."""

    label: str
    refund_cents: int
    credit_cents: int

    def as_dict(self) -> dict:
        return asdict(self)


# Two plans for a 5000-cent order. Both are defensible business decisions.
# They differ in refund amount, which changes any content-derived
# idempotency key, and in whether a second effect is needed at all.
PLAN_FULL = Plan(label="full_refund", refund_cents=5000, credit_cents=0)
PLAN_SPLIT = Plan(label="split_refund_plus_credit", refund_cents=3000, credit_cents=2000)

PLANS = {p.label: p for p in (PLAN_FULL, PLAN_SPLIT)}


class RefundAgent:
    def __init__(self, nondet_p: float | None = None, force_plan: str | None = None):
        self.nondet_p = (
            nondet_p
            if nondet_p is not None
            else float(os.environ.get("BELAY_NONDET_P", "0.5"))
        )
        self.force_plan = force_plan or os.environ.get("BELAY_FORCE_PLAN") or None
        # Fresh entropy per process. A recovering process is not a
        # continuation of the crashed one.
        self._rng = random.Random(os.urandom(16))
        self.invocations = 0

    def decide(self, order_id: str) -> Plan:
        self.invocations += 1
        if self.force_plan:
            # Deterministic mode, used to demonstrate the mechanism on a
            # single run rather than in aggregate.
            plan = PLANS[self.force_plan]
        elif self._rng.random() < self.nondet_p:
            plan = PLAN_SPLIT
        else:
            plan = PLAN_FULL
        return plan
