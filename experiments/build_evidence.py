"""Materialise out-of-band evidence artefacts from the ledger.

This file is grader-side, and that placement is the whole point. It is
allowed to read `services/ledger.py` because it stands in for the outside
world *writing down* what it did; `second/` then reads only the artefacts it
produces. If the adjudicator could reach the ledger directly it would be
reading the answer key, and every number the experiment produced would be
meaningless.

So the artefacts are deliberately lossy views, each modelling a record
system that really exists around a payment processor:

`settlement`
    A batch report. Exhaustive for events at or before `cutoff_ts` and
    silent about everything after, which is how T+1 financial reporting
    actually behaves. Note what it does *not* carry: an anchor. On the
    `opaque` tier the service never received a caller key, so there is
    nothing to record, and the report can be matched only by order and
    amount.

`webhook`
    The processor's own log of delivery attempts, including ones the caller
    never saw. Lossy at `drop_rate`. A hit is proof; silence is worth
    nothing, and the coverage declaration says so.

The five tiers below span the useful range: no evidence at all (the hole
exactly as it is today), evidence that can only confirm, evidence that
arrives too late to cover the window in question, and evidence that settles
it. `stale_settlement` is the interesting one -- silence from a report whose
cutoff precedes the intent looks exactly like proof of absence and is not,
and acting on it issues a duplicate refund.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services.ledger import Ledger  # noqa: E402

# Evidence tiers, worst to best.
NONE = "none"
WEBHOOK_ONLY = "webhook_only"
STALE_SETTLEMENT = "stale_settlement"
SETTLEMENT = "settlement"
BOTH = "both"

TIERS = (NONE, WEBHOOK_ONLY, STALE_SETTLEMENT, SETTLEMENT, BOTH)

TIER_NOTES = {
    NONE: "no out-of-band records at all; the halt stands",
    WEBHOOK_ONLY: "lossy delivery log; can confirm, can never exonerate",
    STALE_SETTLEMENT: "batch report whose cutoff precedes the intent",
    SETTLEMENT: "batch report covering the whole window",
    BOTH: "covering batch report plus a lossy delivery log",
}


def _rows(run_dir: str, order_id: str) -> list[dict]:
    ledger = Ledger(os.path.join(run_dir, "ledger.db"))
    try:
        return [
            {
                "service": r["service"],
                "kind": r["kind"],
                "order_id": r["order_id"],
                "amount_cents": int(r["amount_cents"]),
                "external_id": int(r["id"]),
                "ts": float(r["ts"]),
                # Present but null: the opaque tier received no caller key,
                # so `anchor:` selectors are unanswerable here. The fetcher
                # declines them rather than inventing a match.
                "anchor": r["idem_key"] or r["client_ref"],
            }
            for r in ledger.for_order(order_id)
            if r["service"] == "payments"
        ]
    finally:
        ledger.close()


def _write(evidence_dir: str, source: str, coverage: dict, records: list[dict]) -> None:
    os.makedirs(evidence_dir, exist_ok=True)
    path = os.path.join(evidence_dir, f"{source}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"source": source, "coverage": coverage, "records": records},
            fh,
            indent=2,
            sort_keys=True,
        )


def build(
    run_dir: str,
    order_id: str,
    tier: str,
    *,
    intent_ts: float,
    drop_rate: float = 0.35,
    evidence_dirname: str = "evidence",
    rng: random.Random | None = None,
) -> str:
    """Write the artefacts for one tier. Returns the evidence directory.

    `intent_ts` is the moment the effect may have been attempted. The stale
    tier places its cutoff just before it, which is what makes its silence
    uninformative about this particular effect while leaving it perfectly
    truthful about its own coverage.
    """
    if tier not in TIERS:
        raise ValueError(f"unknown evidence tier {tier!r}")
    rng = rng or random.Random()
    evidence_dir = os.path.join(run_dir, evidence_dirname)
    os.makedirs(evidence_dir, exist_ok=True)
    rows = _rows(run_dir, order_id)

    if tier == NONE:
        return evidence_dir

    if tier in (SETTLEMENT, BOTH):
        cutoff = time.time() + 1.0          # covers the whole window
        _write(
            evidence_dir,
            "settlement",
            {
                "kind": "complete_until",
                "cutoff_ts": cutoff,
                "note": "batch settlement report; exhaustive at or before the "
                        "cutoff, silent about anything later",
            },
            [r for r in rows if r["ts"] <= cutoff],
        )

    if tier == STALE_SETTLEMENT:
        cutoff = intent_ts - 1.0            # stops short of the intent
        _write(
            evidence_dir,
            "settlement",
            {
                "kind": "complete_until",
                "cutoff_ts": cutoff,
                "note": "batch settlement report; exhaustive at or before the "
                        "cutoff, silent about anything later",
            },
            [r for r in rows if r["ts"] <= cutoff],
        )

    if tier in (WEBHOOK_ONLY, BOTH):
        kept = [r for r in rows if rng.random() >= drop_rate]
        _write(
            evidence_dir,
            "webhook",
            {
                "kind": "lossy",
                "drop_rate": drop_rate,
                "note": "delivery attempt log; a hit is proof the effect "
                        "landed, silence proves nothing at any drop rate",
            },
            kept,
        )

    return evidence_dir
