"""Spawn, crash, recover, grade.

The money metric is `total_returned_cents`: every cent the ledger says left
the company for this order, refunds and store credit together. A split plan
of 3000 refund + 2000 credit is correct; 5000 refund + 3000 refund is not.
Counting only refunds would flatter the split plan and understate a
duplicate that straddles both effects.

Grading compares the runtime's *report* against the ledger, which is the
only source of truth about what happened outside the process. A runtime
that says "refunded 5000" while the ledger holds one 3000 refund has not
merely been unlucky; it has told its operator something false.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from belay.authz import PermissionStore  # noqa: E402
from services.ledger import Ledger  # noqa: E402

ALL_SCOPES = ["payments:refund", "credits:issue"]
SIGKILL_EXIT = -9  # subprocess reports a signal death as a negative return code


# Outcome classes, worst to best.
DUPLICATE = "duplicate_effect"          # contract invariant 1 violated
UNAUTHORIZED = "unauthorized_effect"    # contract invariant 2 violated
MISATTRIBUTED = "misattributed"         # reported an outcome that never happened
PHANTOM = "phantom_success"             # claimed success, nothing committed
LOST = "lost_work"                      # crashed, nothing committed, safe but unfinished
ESCALATED = "escalated"                 # invariant 3: halted honestly
REFUSED = "refused"                     # declined before acting
CLEAN = "clean"                         # exactly one effect, reported correctly

FAILURES = {DUPLICATE, UNAUTHORIZED, MISATTRIBUTED, PHANTOM}


@dataclass
class Trial:
    runtime: str
    tier: str
    crash_at: str
    revoke_scope: str | None
    journal_decision: bool
    verdict: str
    n_refunds: int
    refund_amounts: list[int]
    n_credits: int
    credit_amounts: list[int]
    total_returned_cents: int
    reported_refund: int | None
    reported_status: str | None
    plan_first_pass: str | None
    plan_after_recovery: str | None
    diverged: bool | None
    fsyncs: int
    recovery_ms: float | None
    crashed_as_asked: bool
    notes: list[str]
    run_dir: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _spawn(run_dir: str, env_extra: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_extra.items()})
    env["BELAY_RUN_DIR"] = run_dir
    env["PYTHONPATH"] = ROOT
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "worker.py")],
        env=env,
        capture_output=True,
        text=True,
    )


def _read_outcome(run_dir: str, mode: str) -> dict | None:
    path = os.path.join(run_dir, f"outcome.{mode}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _journal(run_dir: str) -> list[dict]:
    path = os.path.join(run_dir, "journal.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break
    return out


def _trace(run_dir: str) -> list[dict]:
    """The observability sidecar. Lets us see decisions a runtime chose not
    to persist. No runtime reads this."""
    path = os.path.join(run_dir, "trace.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break
    return out


def _plan_labels(journal: list[dict]) -> tuple[str | None, str | None, bool | None]:
    """Extract the first-pass plan, the post-recovery plan, and whether the
    agent's decision diverged. Works across all four runtimes' record
    shapes."""
    labels: list[str] = []
    for r in journal:
        if r["kind"] == "decided":
            labels.append(r["plan"]["label"])
        elif r["kind"] == "step_result" and r.get("step") == "decide":
            labels.append(r["value"]["label"])
        elif r["kind"] == "inline_decision":
            labels.append(r["plan"]["label"])
        elif r["kind"] == "divergence_observed":
            labels.append(r["shadow"])
    if not labels:
        return None, None, None
    first = labels[0]
    last = labels[-1]
    return first, last, (first != last) if len(labels) > 1 else False


def run_trial(
    base_dir: str,
    runtime: str,
    tier: str,
    crash_at: str,
    nondet_p: float = 0.5,
    force_plans: tuple[str, str] | None = None,
    revoke_scope: str | None = None,
    journal_decision: bool = True,
    keep: bool = False,
) -> Trial:
    """One crash-and-recover trial.

    force_plans, when given, pins the agent's decision on the first pass and
    on recovery respectively. Used to demonstrate the divergence mechanism
    deterministically instead of waiting for it to occur by chance.
    """
    run_id = uuid.uuid4().hex[:12]
    run_dir = os.path.join(base_dir, f"{runtime}__{tier}__{crash_at}__{run_id}")
    os.makedirs(run_dir, exist_ok=True)

    # Pre-create the ledger and grant every scope.
    Ledger(os.path.join(run_dir, "ledger.db")).close()
    PermissionStore(os.path.join(run_dir, "perms.json")).grant_all(ALL_SCOPES)

    common = {
        "BELAY_RUN_ID": run_id,
        "BELAY_RUNTIME": runtime,
        "BELAY_TIER": tier,
        "BELAY_ORDER_ID": f"order-{run_id}",
        "BELAY_NONDET_P": nondet_p,
        "BELAY_JOURNAL_DECISION": "1" if journal_decision else "0",
    }

    # ---- first pass, armed to crash ----
    first_env = dict(common, BELAY_MODE="run", BELAY_CRASH_AT=crash_at)
    if force_plans:
        first_env["BELAY_FORCE_PLAN"] = force_plans[0]
    p1 = _spawn(run_dir, first_env)
    crashed = p1.returncode == SIGKILL_EXIT

    revoked_at = None
    if crashed and revoke_scope:
        # The operator pulls the permission while the workflow is down.
        PermissionStore(os.path.join(run_dir, "perms.json")).revoke(revoke_scope)
        revoked_at = time.time()

    # ---- recovery pass, no crash armed ----
    recovery_ms = None
    if crashed:
        rec_env = dict(common, BELAY_MODE="recover", BELAY_CRASH_AT="none")
        if force_plans:
            rec_env["BELAY_FORCE_PLAN"] = force_plans[1]
        t0 = time.perf_counter()
        _spawn(run_dir, rec_env)
        recovery_ms = (time.perf_counter() - t0) * 1000

    # ---- grade against the ledger ----
    ledger = Ledger(os.path.join(run_dir, "ledger.db"))
    rows = ledger.for_order(f"order-{run_id}")
    ledger.close()

    refunds = [r for r in rows if r["service"] == "payments"]
    credits = [r for r in rows if r["service"] == "credits"]

    reported = _read_outcome(run_dir, "recover") or _read_outcome(run_dir, "run")
    # Merge the durable journal with the sidecar, in time order, so that
    # decisions a runtime declined to persist are still visible to us.
    merged = sorted(_journal(run_dir) + _trace(run_dir), key=lambda r: r["ts"])
    first_plan, last_plan, diverged = _plan_labels(merged)

    status = reported["status"] if reported else None
    reported_refund = reported.get("reported_refund_cents") if reported else None
    fsyncs = sum(
        (_read_outcome(run_dir, m) or {}).get("fsyncs", 0) for m in ("run", "recover")
    )
    notes = list(reported.get("notes", [])) if reported else ["no report written"]

    unauthorized = bool(
        revoked_at and any(r["ts"] > revoked_at for r in refunds)
    )

    if len(refunds) > 1:
        verdict = DUPLICATE
    elif unauthorized:
        verdict = UNAUTHORIZED
    elif status == "escalated":
        verdict = ESCALATED
    elif status == "refused":
        verdict = REFUSED
    elif status == "committed":
        if not refunds:
            verdict = PHANTOM
        elif reported_refund is not None and refunds[0]["amount_cents"] != reported_refund:
            verdict = MISATTRIBUTED
        else:
            verdict = CLEAN
    elif not refunds:
        verdict = LOST
    else:
        verdict = MISATTRIBUTED

    trial = Trial(
        runtime=runtime,
        tier=tier,
        crash_at=crash_at,
        revoke_scope=revoke_scope,
        journal_decision=journal_decision,
        verdict=verdict,
        n_refunds=len(refunds),
        refund_amounts=[int(r["amount_cents"]) for r in refunds],
        n_credits=len(credits),
        credit_amounts=[int(r["amount_cents"]) for r in credits],
        total_returned_cents=sum(int(r["amount_cents"]) for r in rows),
        reported_refund=reported_refund,
        reported_status=status,
        plan_first_pass=first_plan,
        plan_after_recovery=last_plan,
        diverged=diverged,
        fsyncs=fsyncs,
        recovery_ms=round(recovery_ms, 2) if recovery_ms else None,
        crashed_as_asked=crashed,
        notes=notes,
        run_dir=run_dir if keep else None,
    )

    if not keep:
        shutil.rmtree(run_dir, ignore_errors=True)
    else:
        with open(os.path.join(run_dir, "trial.json"), "w", encoding="utf-8") as fh:
            json.dump(trial.as_dict(), fh, indent=2)

    return trial
