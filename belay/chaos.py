"""Crash injection at named instruction boundaries.

We use a real SIGKILL to the current process rather than raising an
exception. An exception is catchable and lets `finally` blocks run, which
would quietly repair exactly the states we are trying to study. SIGKILL
gives us no unwinding, no flush, no cleanup.

Call sites are named, so a crash lands at a known instruction boundary
instead of a random one. Random termination is also supported
(BELAY_CRASH_AT=random:<p>) but named points are what test the contract.
"""

from __future__ import annotations

import os
import random
import signal
import sys

# This project requires a real SIGKILL, which Windows does not have. Rather
# than fail later with an opaque AttributeError on `signal.SIGKILL`, say so
# here. WSL, Linux and macOS all work.
if not hasattr(signal, "SIGKILL"):  # pragma: no cover - platform guard
    sys.exit(
        "Belay needs POSIX signals: the experiments depend on a real SIGKILL, "
        "because a catchable exception would let `finally` blocks repair the "
        "very states under study. Run on Linux, macOS, or WSL."
    )

# Every crash point in the system. Kept in one place so experiments can
# enumerate them and so a reader can see the whole failure surface at once.
CRASH_POINTS = [
    "none",
    "after_anchor",                 # anchor durable, agent has not decided
    "after_decide_before_journal",  # decision made, NOT durable  <-- divergence window
    "after_intent",                 # intent durable, no external call yet
    "in_flight",                    # service committed, caller has not seen the ack
    "after_ack_before_record",      # caller holds the ack, it is not durable
    "after_effect_a_recorded",      # effect A fully durable, effect B pending
]

_armed: str = "none"
_hits: dict[str, int] = {}
_nth: int = 1


def arm_from_env() -> None:
    global _armed, _nth
    _armed = os.environ.get("BELAY_CRASH_AT", "none")
    _nth = int(os.environ.get("BELAY_CRASH_NTH", "1"))


def armed() -> str:
    return _armed


def maybe_crash(label: str) -> None:
    """Die here if this call site is the armed one.

    Exit status is 137 (128 + SIGKILL), which the harness uses to confirm
    the crash actually happened at the point it asked for.
    """
    global _hits
    if _armed == "none":
        return
    if _armed.startswith("random:"):
        p = float(_armed.split(":", 1)[1])
        if random.random() < p:
            os.kill(os.getpid(), signal.SIGKILL)
        return
    if label != _armed:
        return
    _hits[label] = _hits.get(label, 0) + 1
    if _hits[label] >= _nth:
        os.kill(os.getpid(), signal.SIGKILL)
