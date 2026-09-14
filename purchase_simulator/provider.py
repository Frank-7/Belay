"""Independent fictional USDC-to-USD payout provider for the local demo."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@contextmanager
def _connect(path: Path):
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA synchronous=FULL")
    try:
        with db:
            yield db
    finally:
        db.close()


class ProviderConflict(Exception):
    pass


class DemoPayoutProvider:
    """Records one payout per operation, even when its response is lost."""

    def __init__(self, path):
        self.path = Path(path)
        with _connect(self.path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS payouts_v3 (
                    operation_id TEXT PRIMARY KEY, intent_json TEXT NOT NULL,
                    beneficiary_id TEXT NOT NULL, source_usdc_units INTEGER NOT NULL,
                    net_usd_cents INTEGER NOT NULL, funding_state TEXT NOT NULL,
                    conversion_state TEXT NOT NULL, payout_state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL, provider_reference TEXT NOT NULL
                )"""
            )

    def lookup(self, operation_id):
        with _connect(self.path) as db:
            row = db.execute("SELECT * FROM payouts_v3 WHERE operation_id=?", (operation_id,)).fetchone()
        return dict(row) if row is not None else None

    def submit(self, intent):
        canonical = _encode(intent)
        with _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM payouts_v3 WHERE operation_id=?", (intent["operation_id"],)).fetchone()
            if row is not None:
                if row["intent_json"] != canonical:
                    raise ProviderConflict("operation_id is bound to a different intent")
                db.execute(
                    "UPDATE payouts_v3 SET attempt_count=attempt_count+1 WHERE operation_id=?",
                    (intent["operation_id"],),
                )
                row = db.execute(
                    "SELECT * FROM payouts_v3 WHERE operation_id=?",
                    (intent["operation_id"],),
                ).fetchone()
                return dict(row)
            reference = "pout_demo_" + intent["operation_id"][-12:]
            db.execute(
                "INSERT INTO payouts_v3 VALUES(?,?,?,?,?,?,?,?,?,?)",
                (intent["operation_id"], canonical, intent["beneficiary_id"], intent["source_usdc_units"], intent["net_usd_cents"], "received", "pending", "pending", 1, reference),
            )
            row = db.execute("SELECT * FROM payouts_v3 WHERE operation_id=?", (intent["operation_id"],)).fetchone()
            return dict(row)

    def convert(self, operation_id):
        with _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM payouts_v3 WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise ProviderConflict("payout operation is missing")
            if row["conversion_state"] == "pending":
                db.execute("UPDATE payouts_v3 SET conversion_state='converted' WHERE operation_id=?", (operation_id,))
        return self.lookup(operation_id)

    def complete(self, operation_id):
        with _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM payouts_v3 WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None or row["conversion_state"] != "converted":
                raise ProviderConflict("conversion has not completed")
            if row["payout_state"] != "paid":
                db.execute("UPDATE payouts_v3 SET funding_state='settled', payout_state='paid' WHERE operation_id=?", (operation_id,))
        return self.lookup(operation_id)

    def seed_historical(self, intent):
        row = self.submit(intent)
        if row["conversion_state"] != "converted":
            row = self.convert(intent["operation_id"])
        if row["payout_state"] != "paid":
            row = self.complete(intent["operation_id"])
        return row
