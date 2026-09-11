#!/usr/bin/env python3
"""The crashable process.

Spawned by the harness. Executes one pass of the refund workflow under one
runtime, and may be SIGKILLed partway through by `belay.chaos`.

Writes `outcome.json` on a clean finish. The absence of that file is how
the harness knows the process died without reporting.

Environment:
    BELAY_RUN_DIR    working directory for journal / ledger / perms
    BELAY_RUN_ID     stable id for this logical workflow across restarts
    BELAY_RUNTIME    naive | replay_position | replay_content | anchored
    BELAY_TIER       idempotent | queryable | opaque
    BELAY_MODE       run | recover
    BELAY_ORDER_ID   order under refund
    BELAY_CRASH_AT   a label from belay.chaos.CRASH_POINTS, or none
    BELAY_NONDET_P   P(agent picks the split plan) per invocation
    BELAY_FORCE_PLAN full_refund | split_refund_plus_credit (overrides p)
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from belay import chaos  # noqa: E402
from belay.runtimes import RUNTIMES  # noqa: E402
from belay.runtimes.base import Ctx, Outcome, Status  # noqa: E402


def main() -> int:
    chaos.arm_from_env()

    run_dir = os.environ["BELAY_RUN_DIR"]
    mode = os.environ.get("BELAY_MODE", "run")
    runtime = RUNTIMES[os.environ["BELAY_RUNTIME"]]

    ctx = Ctx(
        run_dir=run_dir,
        run_id=os.environ["BELAY_RUN_ID"],
        order_id=os.environ.get("BELAY_ORDER_ID", "order-1"),
        tier=os.environ["BELAY_TIER"],
    )

    t0 = time.perf_counter()
    try:
        outcome: Outcome = runtime.run(ctx) if mode == "run" else runtime.recover(ctx)
    except Exception as exc:  # a bug in a runtime should be visible, not silent
        outcome = Outcome(Status.INCOMPLETE, notes=[f"{type(exc).__name__}: {exc}"])
    elapsed_ms = (time.perf_counter() - t0) * 1000

    payload = outcome.as_dict()
    payload.update(
        {
            "mode": mode,
            "runtime": os.environ["BELAY_RUNTIME"],
            "tier": os.environ["BELAY_TIER"],
            "fsyncs": ctx.journal.fsync_count,
            "elapsed_ms": round(elapsed_ms, 3),
            "agent_invocations": ctx.agent.invocations,
        }
    )

    path = os.path.join(run_dir, f"outcome.{mode}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
