"""Durable Belay v0.3 investor simulation.

Only the browser-to-loopback-server connection is real. The agent, merchant,
USDC transfer, conversion, USD payout, delivery evidence and protection reserve
are local fixtures. No external service, wallet, chain or bank is contacted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from purchase_simulator.policy import PolicyDecision, evaluate
from purchase_simulator.provider import DemoPayoutProvider, ProviderConflict

SCHEMA_VERSION = "belay.purchase.v0.3"
USDC_SCALE = 1_000_000
USDC_PER_USD_CENT = 10_000
EVENT = "The Midnight Signals"
DATE = "2026-10-24"
VENUE = "Harbor Hall, Boston"
SELLER = "Northstar Tickets"
SELLER_ID = "merchant_northstar_demo"
UNIT_PRICE_CENTS = 10_000
RESERVE_UNITS = 1_000 * USDC_SCALE
COVERAGE_MAX_UNITS = 300 * USDC_SCALE
NOTICE = (
    "Interactive local simulation. All balances, tickets, providers, signatures, "
    "coverage and credentials are fictional. No live money, blockchain, bank, "
    "merchant, insurer, exchange or model is connected."
)
SCENARIOS = [
    {
        "id": "success",
        "label": "Delivered — protected purchase",
        "description": "Belay buys exactly two $100 tickets, pays the merchant in USD, and verifies delivery.",
    },
    {
        "id": "payout_reply_lost",
        "label": "Payout reply lost — recover safely",
        "description": "The merchant is paid once. Belay retrieves the exact payout instead of sending another.",
    },
    {
        "id": "non_delivery_paid",
        "label": "Merchant paid — tickets missing",
        "description": "The merchant keeps the original $200 while Belay restores 200 USDC from its reserve.",
    },
    {
        "id": "quantity_violation",
        "label": "Agent proposes three — blocked",
        "description": "The agent proposes three tickets; deterministic controls stop it before any funds move.",
    },
    {
        "id": "historical_agent_error",
        "label": "Injected past error — buyer restored",
        "description": "A labeled historical fixture already bought three; a contractual agent-error remedy returns the unauthorized 100 USDC.",
    },
    {
        "id": "cancel_before_dispatch",
        "label": "Cancel before dispatch",
        "description": "A reserved purchase is cancelled before USDC leaves Belay, so the hold returns immediately.",
    },
    {
        "id": "evidence_conflict",
        "label": "Evidence conflicts — review",
        "description": "Conflicting delivery evidence pauses the claim without paying either side twice.",
    },
]
CREDENTIALS = [
    {
        "name": "Customer grant key reference",
        "key": "demo:keyref:customer:7f4a",
        "holder": "Belay authorization service",
        "purpose": "A fake protected-key reference. The shopping model never receives signing material.",
    },
    {
        "name": "Agent capability token",
        "key": "demo_cap_ticket_search_readonly",
        "holder": "Shopping agent",
        "purpose": "A fictional token limited to offers; it cannot move funds.",
    },
    {
        "name": "Treasury execution credential",
        "key": "demo_treasury_executor_NOT_REAL",
        "holder": "Deterministic executor",
        "purpose": "Illustrates the isolated component allowed to dispatch an admitted transfer.",
    },
    {
        "name": "Conversion provider credential",
        "key": "demo_fx_provider_key_NOT_REAL",
        "holder": "Settlement adapter",
        "purpose": "A non-working fixture for a provider that receives USDC and pays a merchant in USD.",
    },
]


class DemoError(Exception):
    def __init__(self, message: str, status: int = 400, current: dict | None = None):
        super().__init__(message)
        self.status = status
        self.current = current


@contextmanager
def connect(path: Path):
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    try:
        with db:
            yield db
    finally:
        db.close()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return "sha256:" + hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


class Engine:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "app.sqlite3"
        self.provider_path = self.data_dir / "provider.sqlite3"
        self.lock = threading.RLock()
        self.provider = DemoPayoutProvider(self.provider_path)
        with connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, state_json TEXT NOT NULL)")
            db.execute(
                """CREATE TABLE IF NOT EXISTS treasury_accounts_v3 (
                    run_id TEXT NOT NULL, account TEXT NOT NULL, asset TEXT NOT NULL,
                    units INTEGER NOT NULL CHECK(units >= 0),
                    PRIMARY KEY(run_id, account, asset)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS coverage_v3 (
                    run_id TEXT NOT NULL, order_id TEXT NOT NULL,
                    max_units INTEGER NOT NULL, committed_units INTEGER NOT NULL,
                    pending_units INTEGER NOT NULL, paid_units INTEGER NOT NULL,
                    status TEXT NOT NULL, PRIMARY KEY(run_id, order_id)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS ledger_entries_v3 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
                    account_from TEXT, account_to TEXT, asset TEXT NOT NULL,
                    units INTEGER NOT NULL CHECK(units >= 0), kind TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS claims_v3 (
                    case_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, order_id TEXT NOT NULL,
                    economic_loss_id TEXT NOT NULL UNIQUE, loss_type TEXT NOT NULL,
                    status TEXT NOT NULL, requested_units INTEGER NOT NULL,
                    approved_units INTEGER NOT NULL,
                    paid_units INTEGER NOT NULL, evidence_json TEXT NOT NULL
                )"""
            )
            claim_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(claims_v3)")
            }
            if "requested_units" not in claim_columns:
                db.execute(
                    "ALTER TABLE claims_v3 ADD COLUMN requested_units INTEGER NOT NULL DEFAULT 0"
                )
            db.execute(
                """UPDATE claims_v3 SET requested_units=CASE loss_type
                       WHEN 'supplier_non_delivery' THEN ?
                       WHEN 'ambiguous_delivery' THEN ?
                       WHEN 'agent_quantity_error' THEN ?
                       ELSE requested_units END
                   WHERE requested_units=0""",
                (200 * USDC_SCALE, 200 * USDC_SCALE, 100 * USDC_SCALE),
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS settlements_v3 (
                    operation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    order_id TEXT NOT NULL, intent_digest TEXT NOT NULL,
                    provider_reference TEXT NOT NULL, beneficiary_id TEXT NOT NULL,
                    source_asset TEXT NOT NULL, source_units INTEGER NOT NULL,
                    destination_asset TEXT NOT NULL, net_destination_units INTEGER NOT NULL,
                    payout_state TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS order_authority_v3 (
                    run_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE,
                    operation_id TEXT NOT NULL UNIQUE, record_type TEXT NOT NULL,
                    grant_json TEXT NOT NULL, offer_json TEXT NOT NULL,
                    quote_json TEXT NOT NULL, grant_digest TEXT NOT NULL,
                    offer_digest TEXT NOT NULL, quote_digest TEXT NOT NULL,
                    source_usdc_units INTEGER NOT NULL,
                    beneficiary_id TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS delivery_outcomes_v3 (
                    run_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE,
                    delivery_state TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    evidence_digest TEXT NOT NULL
                )"""
            )

    def close(self):
        """Connections are scoped to operations; nothing remains open."""

    def config(self):
        return json.loads(
            encode(
                {
                    "schema_version": SCHEMA_VERSION,
                    "scenarios": SCENARIOS,
                    "credentials": CREDENTIALS,
                    "notice": NOTICE,
                    "demo_assumptions": {
                        "usdc_decimals": 6,
                        "fx_rate": "1 USDC = 1.00 USD",
                        "fees": "0 in this simulation",
                        "merchant_receives": "USD",
                    },
                }
            )
        )

    def _read(self, db, run_id):
        if not isinstance(run_id, str):
            raise DemoError("Run not found", 404)
        row = db.execute("SELECT state_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DemoError("Run not found", 404)
        state = json.loads(row["state_json"])
        if state.get("schema_version") != SCHEMA_VERSION:
            raise DemoError("This saved run uses an older demo version. Start a new simulation.", 410)
        return state

    def _account(self, db, run_id, account, asset):
        row = db.execute(
            "SELECT units FROM treasury_accounts_v3 WHERE run_id=? AND account=? AND asset=?",
            (run_id, account, asset),
        ).fetchone()
        return int(row["units"]) if row else 0

    def _set_account(self, db, run_id, account, asset, units):
        db.execute(
            """INSERT INTO treasury_accounts_v3(run_id,account,asset,units)
               VALUES(?,?,?,?) ON CONFLICT(run_id,account,asset)
               DO UPDATE SET units=excluded.units""",
            (run_id, account, asset, units),
        )

    def _move(self, db, state, key, source, destination, asset, units, kind):
        prior = db.execute(
            """SELECT run_id,account_from,account_to,asset,units,kind
               FROM ledger_entries_v3 WHERE idempotency_key=?""",
            (key,),
        ).fetchone()
        if prior:
            expected = (state["id"], source, destination, asset, units, kind)
            observed = tuple(prior[field] for field in (
                "run_id", "account_from", "account_to", "asset", "units", "kind"
            ))
            if observed != expected:
                raise DemoError("Idempotency key is bound to a different ledger movement", 409)
            return False
        source_units = self._account(db, state["id"], source, asset)
        if source_units < units:
            raise DemoError(f"Insufficient {asset} in {source}", 409)
        self._set_account(db, state["id"], source, asset, source_units - units)
        destination_units = self._account(db, state["id"], destination, asset)
        self._set_account(db, state["id"], destination, asset, destination_units + units)
        db.execute(
            """INSERT INTO ledger_entries_v3
               (run_id,idempotency_key,account_from,account_to,asset,units,kind,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (state["id"], key, source, destination, asset, units, kind, int(time.time())),
        )
        return True

    def _record_conversion(self, db, state, provider):
        key = f"{state['order_id']}:merchant-paid"
        settlement_expected = self._settlement_values(state, provider)
        prior_settlement = db.execute(
            "SELECT * FROM settlements_v3 WHERE operation_id=?",
            (state["operation_id"],),
        ).fetchone()
        prior_ledger = db.execute(
            """SELECT run_id,account_from,account_to,asset,units,kind
               FROM ledger_entries_v3 WHERE idempotency_key=?""",
            (key,),
        ).fetchone()
        ledger_expected = (
            state["id"], "provider_in_transit", "merchant_received",
            "USDC_TO_USD_1_TO_1_DEMO", provider["source_usdc_units"],
            "conversion_and_merchant_payout",
        )
        if prior_settlement is not None:
            settlement_observed = tuple(prior_settlement[field] for field in (
                "operation_id", "run_id", "order_id", "intent_digest",
                "provider_reference", "beneficiary_id", "source_asset",
                "source_units", "destination_asset", "net_destination_units",
                "payout_state",
            ))
            if settlement_observed != settlement_expected:
                raise DemoError("Payout identity is bound to a different settlement", 409)
            if prior_ledger is None:
                raise DemoError("Settlement record exists without its value movement", 409)
            ledger_observed = tuple(prior_ledger[field] for field in (
                "run_id", "account_from", "account_to", "asset", "units", "kind"
            ))
            if ledger_observed != ledger_expected:
                raise DemoError("Payout identity is bound to a different settlement", 409)
            return False
        if prior_ledger is not None:
            raise DemoError("Value movement exists without its settlement record", 409)
        source_units = self._account(db, state["id"], "provider_in_transit", "USDC")
        if source_units < provider["source_usdc_units"]:
            raise DemoError("Provider settlement balance is insufficient", 409)
        self._set_account(db, state["id"], "provider_in_transit", "USDC", source_units - provider["source_usdc_units"])
        current_usd = self._account(db, state["id"], "merchant_received", "USD_CENTS")
        self._set_account(db, state["id"], "merchant_received", "USD_CENTS", current_usd + provider["net_usd_cents"])
        db.execute(
            """INSERT INTO ledger_entries_v3
               (run_id,idempotency_key,account_from,account_to,asset,units,kind,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (state["id"], key, "provider_in_transit", "merchant_received", "USDC_TO_USD_1_TO_1_DEMO", provider["source_usdc_units"], "conversion_and_merchant_payout", int(time.time())),
        )
        db.execute(
            """INSERT INTO settlements_v3
               (operation_id,run_id,order_id,intent_digest,provider_reference,
                beneficiary_id,source_asset,source_units,destination_asset,
                net_destination_units,payout_state)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            settlement_expected,
        )
        return True

    def _settlement_values(self, state, provider):
        return (
            state["operation_id"], state["id"], state["order_id"],
            digest(state["intent"]), provider["provider_reference"],
            provider["beneficiary_id"], state["fx_quote"]["source_asset"],
            provider["source_usdc_units"], state["fx_quote"]["destination_asset"],
            provider["net_usd_cents"], provider["payout_state"],
        )

    def _authority_values(self, state, record_type):
        return (
            state["id"], state["order_id"], state["operation_id"], record_type,
            encode(state["grant"]), encode(state["offer"]), encode(state["fx_quote"]),
            digest(state["grant"]), digest(state["offer"]), digest(state["fx_quote"]),
            state["fx_quote"]["source_usdc_units"],
            state["fx_quote"]["beneficiary_id"],
        )

    def _record_order_authority(self, db, state, record_type):
        expected = self._authority_values(state, record_type)
        prior = db.execute(
            "SELECT * FROM order_authority_v3 WHERE run_id=? OR order_id=? OR operation_id=?",
            (state["id"], state["order_id"], state["operation_id"]),
        ).fetchone()
        fields = (
            "run_id", "order_id", "operation_id", "record_type", "grant_json",
            "offer_json", "quote_json", "grant_digest", "offer_digest",
            "quote_digest", "source_usdc_units", "beneficiary_id",
        )
        if prior is not None:
            if tuple(prior[field] for field in fields) != expected:
                raise DemoError("Order authority identity is bound to different terms", 409)
            return False
        db.execute(
            """INSERT INTO order_authority_v3
               (run_id,order_id,operation_id,record_type,grant_json,offer_json,
                quote_json,grant_digest,offer_digest,quote_digest,
                source_usdc_units,beneficiary_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            expected,
        )
        return True

    def _delivery_evidence(self, state):
        if state["scenario"] == "historical_agent_error":
            return {
                "record_type": "historical_import",
                "purchased_quantity": 3,
                "tickets_released_to_customer": state["tickets"],
                "unauthorized_item": state["unauthorized_item"],
            }
        if state["delivery_state"] == "not_delivered":
            return {
                "record_type": "delivery_check",
                "order_id": state["order_id"],
                "tickets_received": 0,
            }
        if state["delivery_state"] == "evidence_conflict":
            return {
                "record_type": "conflicting_sources",
                "merchant_status": "delivered",
                "customer_wallet_status": "missing",
            }
        return {
            "record_type": "verified_ticket_delivery",
            "order_id": state["order_id"],
            "expected_quantity": 2,
            "tickets": state["tickets"],
        }

    def _delivery_values(self, state):
        evidence = self._delivery_evidence(state)
        return (
            state["id"], state["order_id"], state["delivery_state"],
            encode(evidence), digest(evidence),
        )

    def _record_delivery_outcome(self, db, state):
        expected = self._delivery_values(state)
        prior = db.execute(
            "SELECT * FROM delivery_outcomes_v3 WHERE run_id=? OR order_id=?",
            (state["id"], state["order_id"]),
        ).fetchone()
        fields = (
            "run_id", "order_id", "delivery_state", "evidence_json",
            "evidence_digest",
        )
        if prior is not None:
            if tuple(prior[field] for field in fields) != expected:
                raise DemoError("Delivery record is bound to different evidence", 409)
            return False
        db.execute(
            """INSERT INTO delivery_outcomes_v3
               (run_id,order_id,delivery_state,evidence_json,evidence_digest)
               VALUES(?,?,?,?,?)""",
            expected,
        )
        return True

    def _coverage(self, db, state):
        row = db.execute(
            "SELECT * FROM coverage_v3 WHERE run_id=? AND order_id=?",
            (state["id"], state["order_id"]),
        ).fetchone()
        if row is None:
            return {"max_units": 0, "committed_units": 0, "pending_units": 0, "paid_units": 0, "status": "not_reserved"}
        return dict(row)

    def _reserve_coverage(self, db, state):
        if self._coverage(db, state)["max_units"]:
            return
        reserve = self._account(db, state["id"], "protection_reserve", "USDC")
        outstanding = db.execute(
            "SELECT COALESCE(SUM(committed_units + pending_units), 0) AS total FROM coverage_v3 WHERE run_id=?",
            (state["id"],),
        ).fetchone()["total"]
        if reserve - outstanding < COVERAGE_MAX_UNITS:
            raise DemoError("Protection reserve has insufficient available capacity", 409)
        db.execute(
            "INSERT INTO coverage_v3 VALUES(?,?,?,?,?,?,?)",
            (state["id"], state["order_id"], COVERAGE_MAX_UNITS, COVERAGE_MAX_UNITS, 0, 0, "committed"),
        )

    def _release_coverage(self, db, state, status="closed"):
        db.execute(
            "UPDATE coverage_v3 SET committed_units=0, status=? WHERE run_id=? AND order_id=?",
            (status, state["id"], state["order_id"]),
        )

    def _open_claim(self, db, state, loss_type, amount, evidence):
        loss_id = f"{state['order_id']}:{loss_type}"
        evidence_json = encode(evidence)
        prior = db.execute(
            """SELECT * FROM claims_v3
               WHERE case_id=? OR economic_loss_id=?""",
            (state["case_id"], loss_id),
        ).fetchone()
        if prior is not None:
            expected = (
                state["case_id"], state["id"], state["order_id"], loss_id,
                loss_type, amount, evidence_json,
            )
            observed = tuple(prior[field] for field in (
                "case_id", "run_id", "order_id", "economic_loss_id",
                "loss_type", "requested_units", "evidence_json",
            ))
            if observed != expected:
                raise DemoError("Claim identity is bound to different evidence or loss", 409)
            state["claim_amount_usdc_units"] = amount
            return
        db.execute(
            """INSERT INTO claims_v3
               (case_id,run_id,order_id,economic_loss_id,loss_type,status,
                requested_units,approved_units,paid_units,evidence_json)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                state["case_id"], state["id"], state["order_id"], loss_id,
                loss_type, "open", amount, 0, 0, evidence_json,
            ),
        )
        state["claim_amount_usdc_units"] = amount

    def _approve_claim(self, db, state):
        claim = db.execute("SELECT * FROM claims_v3 WHERE case_id=?", (state["case_id"],)).fetchone()
        if claim is None:
            raise DemoError("Claim case is missing", 409)
        amount = int(claim["requested_units"])
        if amount <= 0:
            raise DemoError("Claim has no persisted requested amount", 409)
        if claim["status"] in ("approved", "paid"):
            if int(claim["approved_units"]) != amount:
                raise DemoError("Approved claim does not match its requested amount", 409)
            state["claim_amount_usdc_units"] = amount
            return
        coverage = self._coverage(db, state)
        if amount > coverage["committed_units"]:
            raise DemoError("Claim exceeds unused order coverage", 409)
        coverage_update = db.execute(
            """UPDATE coverage_v3 SET committed_units=committed_units-?,
               pending_units=pending_units+?, status='claim_approved'
               WHERE run_id=? AND order_id=? AND committed_units>=?""",
            (amount, amount, state["id"], state["order_id"], amount),
        )
        updated = db.execute(
            """UPDATE claims_v3 SET status='approved',approved_units=?
               WHERE case_id=? AND status='open' AND requested_units=?""",
            (amount, state["case_id"], amount),
        )
        if coverage_update.rowcount != 1 or updated.rowcount != 1:
            raise DemoError("Claim changed during approval", 409)
        state["claim_amount_usdc_units"] = amount

    def _pay_claim(self, db, state):
        claim = db.execute("SELECT * FROM claims_v3 WHERE case_id=?", (state["case_id"],)).fetchone()
        if claim is None:
            raise DemoError("Claim is missing", 409)
        amount = int(claim["approved_units"])
        if amount <= 0:
            raise DemoError("Claim has no persisted approved amount", 409)
        if claim["status"] == "paid":
            if int(claim["paid_units"]) != amount:
                raise DemoError("Paid claim does not match its approved amount", 409)
            return amount
        if claim["status"] != "approved":
            raise DemoError("Claim is not approved", 409)
        coverage = self._coverage(db, state)
        if coverage["pending_units"] < amount or coverage["paid_units"] != 0:
            raise DemoError("Protection ledger does not match the approved claim", 409)
        if not self._move(
            db, state, f"claim:{state['case_id']}:pay", "protection_reserve",
            "customer_available", "USDC", amount, "protection_payout",
        ):
            raise DemoError("Claim payout ledger already exists before claim completion", 409)
        coverage_update = db.execute(
            """UPDATE coverage_v3 SET pending_units=pending_units-?,
               paid_units=?, status='claim_paid'
               WHERE run_id=? AND order_id=? AND pending_units>=? AND paid_units=0""",
            (amount, amount, state["id"], state["order_id"], amount),
        )
        claim_update = db.execute(
            """UPDATE claims_v3 SET status='paid',paid_units=?
               WHERE case_id=? AND status='approved' AND approved_units=? AND paid_units=0""",
            (amount, state["case_id"], amount),
        )
        if coverage_update.rowcount != 1 or claim_update.rowcount != 1:
            raise DemoError("Claim payout state changed during settlement", 409)
        state["claim_amount_usdc_units"] = amount
        return amount

    def _snapshot(self, state, db=None):
        owns_connection = db is None
        if owns_connection:
            db = sqlite3.connect(str(self.path), timeout=10)
            db.row_factory = sqlite3.Row
        try:
            run_id = state["id"]
            accounts = {row["account"]: int(row["units"]) for row in db.execute(
                "SELECT account,units FROM treasury_accounts_v3 WHERE run_id=?", (run_id,)
            )}
            coverage = self._coverage(db, state)
            claims = [dict(row) for row in db.execute(
                "SELECT * FROM claims_v3 WHERE run_id=? ORDER BY case_id", (run_id,)
            )]
            for claim in claims:
                claim["evidence"] = json.loads(claim.pop("evidence_json"))
            ledger = [dict(row) for row in db.execute(
                """SELECT idempotency_key,account_from,account_to,asset,units,kind
                   FROM ledger_entries_v3 WHERE run_id=? ORDER BY id""", (run_id,)
            )]
            settlement_record = db.execute(
                "SELECT * FROM settlements_v3 WHERE run_id=?", (run_id,)
            ).fetchone()
            delivery_record = db.execute(
                "SELECT * FROM delivery_outcomes_v3 WHERE run_id=?", (run_id,)
            ).fetchone()
            provider = self.provider.lookup(state["operation_id"])
            result = json.loads(encode(state))
            committed = int(coverage["committed_units"])
            pending = int(coverage["pending_units"])
            reserve_cash = accounts.get("protection_reserve", 0)
            result["buyer"] = {
                "available_usdc_units": accounts.get("customer_available", 0),
                "held_usdc_units": accounts.get("order_hold", 0),
            }
            result["settlement"] = {
                "provider_in_transit_usdc_units": accounts.get("provider_in_transit", 0),
                "merchant_received_usd_cents": accounts.get("merchant_received", 0),
                "provider_observed_usd_cents": int(provider["net_usd_cents"])
                if provider and provider["payout_state"] == "paid" else 0,
                "provider_payout_count": int(bool(provider and provider["payout_state"] == "paid")),
                "provider_attempt_count": int(provider["attempt_count"]) if provider else 0,
            }
            result["protection"] = {
                "reserve_cash_usdc_units": reserve_cash,
                "max_usdc_units": int(coverage["max_units"]),
                "committed_usdc_units": committed,
                "pending_usdc_units": pending,
                "paid_usdc_units": int(coverage["paid_units"]),
                "available_usdc_units": max(0, reserve_cash - committed - pending),
                "status": coverage["status"],
            }
            result["claims"] = claims
            result["ledger"] = ledger
            result["settlement_record"] = (
                dict(settlement_record) if settlement_record is not None else None
            )
            if delivery_record is None:
                result["delivery_record"] = None
            else:
                result["delivery_record"] = dict(delivery_record)
                result["delivery_record"]["evidence"] = json.loads(
                    result["delivery_record"].pop("evidence_json")
                )
            result["provider"] = {key: value for key, value in (provider or {}).items() if key != "intent_json"}
            result["provider_payout_count"] = result["settlement"]["provider_payout_count"]
            result["budget"] = {
                "available_cents": result["buyer"]["available_usdc_units"] // USDC_PER_USD_CENT,
                "reserved_cents": result["buyer"]["held_usdc_units"] // USDC_PER_USD_CENT,
                "spent_cents": result["settlement"]["merchant_received_usd_cents"],
            }
            return result
        finally:
            if owns_connection:
                db.close()

    def get(self, run_id):
        with self.lock, connect(self.path) as db:
            return self._snapshot(self._read(db, run_id), db)

    def _event(
        self, state, *, step, stage, title, explanation, actor, sender,
        recipient, method, url, status=200, request=None, response=None,
    ):
        state.update(step=step, stage=stage, title=title, explanation=explanation)
        state["events"].append({
            "id": f"{state['id']}:{state['revision']}", "step": step,
            "title": title, "explanation": explanation, "actor": actor,
            "from": sender, "to": recipient, "method": method, "url": url,
            "status": status, "request": request or {}, "response": response or {},
        })

    def create(self, scenario, budget_cents, quantity=2):
        if not isinstance(scenario, str) or scenario not in {item["id"] for item in SCENARIOS}:
            raise DemoError("Choose a supported scenario")
        if type(budget_cents) is not int or not 20_000 <= budget_cents <= 1_000_000:
            raise DemoError("budget_cents must be an integer from 20000 to 1000000")
        if type(quantity) is not int or quantity != 2:
            raise DemoError("This demonstration grants authority for exactly two tickets")
        with self.lock, connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            run_id = uuid.uuid4().hex
            operation_id = "settle_" + uuid.uuid4().hex
            order_id = "ord_" + uuid.uuid4().hex[:20]
            case_id = "case_" + uuid.uuid4().hex[:20]
            issued_at = int(time.time())
            mission = {
                "event": EVENT, "date": DATE, "time": "8:00 PM ET", "venue": VENUE,
                "quantity": quantity, "max_total_usdc_units": budget_cents * USDC_PER_USD_CENT,
                "max_total_usd_cents": budget_cents,
            }
            grant = {
                **mission, "seller_id": SELLER_ID, "adjacent": True, "approved": True,
                "issued_at": issued_at, "expires_at": issued_at + 1800,
                "signature": "mocksig:customer-grant:approved",
            }
            historical = scenario == "historical_agent_error"
            max_steps = {
                "success": 12,
                "payout_reply_lost": 12,
                "non_delivery_paid": 13,
                "quantity_violation": 3,
                "historical_agent_error": 5,
                "cancel_before_dispatch": 5,
                "evidence_conflict": 11,
            }
            state = {
                "schema_version": SCHEMA_VERSION, "id": run_id, "scenario": scenario,
                "entry_mode": "injected_historical_fixture" if historical else "live_guarded_simulation",
                "revision": 0, "step": 0, "max_step": max_steps[scenario],
                "stage": "historical_fixture_loaded" if historical else "mission_authorized",
                "title": "Historical paid order loaded" if historical else "Bounded mission authorized",
                "explanation": "The customer funds a bounded USDC grant and permits exactly two tickets.",
                "terminal": False, "can_advance": True, "needs_verification": False,
                "manual_review": False,
                "user_message": "I found the mission boundary: exactly two adjacent tickets, up to 300 USDC.",
                "outcome": {"kind": "active", "headline": "Mission ready", "detail": "No merchant payment has been sent."},
                "mission": mission, "grant": grant, "offer": None, "fx_quote": None,
                "policy_decision": None, "admission": None,
                "operation_id": operation_id, "order_id": order_id,
                "case_id": case_id, "claim_amount_usdc_units": 0,
                "funding_state": "funded_grant", "conversion_state": "not_started",
                "payout_state": "not_started", "order_state": "not_submitted",
                "delivery_state": "not_started", "protection_state": "not_reserved",
                "recovery_state": "not_needed", "events": [], "tickets": [],
                "payout_evidence": None, "unauthorized_item": None, "receipt": None,
            }
            customer_units = budget_cents * USDC_PER_USD_CENT
            if historical:
                if budget_cents < 30_000:
                    raise DemoError("The injected historical case requires a 300 USDC demo budget")
                customer_units -= 300 * USDC_SCALE
                state.update(
                    funding_state="settled", conversion_state="converted", payout_state="paid",
                    order_state="confirmed_with_error", delivery_state="delivered_three",
                    protection_state="committed", recovery_state="agent_error_detected",
                    user_message="Audit loaded: an earlier executor bought three tickets although the grant allowed two.",
                    outcome={"kind": "warning", "headline": "Injected historical defect", "detail": "This starts after a fictional prior payment; the live policy guard was not bypassed."},
                )
                state["tickets"] = [
                    {"section": "102", "row": "H", "seat": "12", "holder": "Alex Morgan"},
                    {"section": "102", "row": "H", "seat": "13", "holder": "Alex Morgan"},
                ]
                state["unauthorized_item"] = {
                    "section": "102", "row": "H", "seat": "14",
                    "status": "quarantined_for_return_or_resale",
                    "customer_access": False,
                }
                state["offer"] = self._offer(3)
                state["fx_quote"] = self._quote(operation_id, 3)
            for account, asset, units in (
                ("customer_available", "USDC", customer_units),
                ("order_hold", "USDC", 0),
                ("provider_in_transit", "USDC", 0),
                ("merchant_received", "USD_CENTS", 30_000 if historical else 0),
                ("protection_reserve", "USDC", RESERVE_UNITS),
            ):
                self._set_account(db, run_id, account, asset, units)
            if historical:
                db.execute(
                    "INSERT INTO coverage_v3 VALUES(?,?,?,?,?,?,?)",
                    (run_id, order_id, COVERAGE_MAX_UNITS, COVERAGE_MAX_UNITS, 0, 0, "committed"),
                )
                state["intent"] = self._intent(state, quantity=3)
                self._record_order_authority(db, state, "historical_import")
                self._record_delivery_outcome(db, state)
                provider = self.provider.seed_historical(state["intent"])
                db.execute(
                    """INSERT INTO settlements_v3
                       (operation_id,run_id,order_id,intent_digest,provider_reference,
                        beneficiary_id,source_asset,source_units,destination_asset,
                        net_destination_units,payout_state)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    self._settlement_values(state, provider),
                )
                state["payout_evidence"] = {
                    "provider_reference": provider["provider_reference"],
                    "operation_id": operation_id,
                    "net_usd_cents": provider["net_usd_cents"],
                    "payout_state": provider["payout_state"],
                }
            self._event(
                state, step=0, stage=state["stage"], title=state["title"],
                explanation=state["outcome"]["detail"] if historical else state["explanation"],
                actor="Belay audit importer" if historical else "Customer", sender="Customer",
                recipient="Belay authority service", method="POST", url="/api/runs", status=201,
                request={"scenario": scenario, "mission": mission},
                response={"entry_mode": state["entry_mode"], "grant_id": "grant_" + run_id[:16], "operation_id": operation_id},
            )
            db.execute("INSERT INTO runs VALUES(?,?)", (run_id, encode(state)))
            return self._snapshot(state, db)

    def _offer(self, quantity):
        return {
            "offer_id": "offer_northstar_demo", "event": EVENT, "date": DATE,
            "venue": VENUE, "seller": SELLER, "seller_id": SELLER_ID,
            "quantity": quantity, "adjacent": True,
            "seats": ["102-H-12", "102-H-13", "102-H-14"][:quantity],
            "unit_price_usd_cents": UNIT_PRICE_CENTS,
            "total_usd_cents": UNIT_PRICE_CENTS * quantity,
        }

    def _quote(self, operation_id, quantity):
        total = UNIT_PRICE_CENTS * quantity
        issued_at = int(time.time())
        return {
            "quote_id": "fxq_" + operation_id[-12:], "source_asset": "USDC",
            "source_usdc_units": total * USDC_PER_USD_CENT,
            "destination_asset": "USD", "merchant_net_usd_cents": total,
            "rate": "1.000000 USDC/USD", "fee_usdc_units": 0,
            "beneficiary_id": SELLER_ID, "issued_at": issued_at,
            "expires_at": issued_at + 120, "expires_in_seconds": 120,
            "demo_only": True,
        }

    def _intent(self, state, quantity=None):
        offer = state["offer"]
        amount = offer["total_usd_cents"]
        return {
            "schema": "belay.settlement-intent.v0.3-demo",
            "operation_id": state["operation_id"], "order_id": state["order_id"],
            "grant_digest": digest(state["grant"]), "offer_digest": digest(offer),
            "quote_digest": digest(state["fx_quote"]),
            "quantity": quantity if quantity is not None else offer["quantity"],
            "beneficiary_id": SELLER_ID,
            "source_asset": "USDC", "destination_asset": "USD",
            "source_usdc_units": amount * USDC_PER_USD_CENT, "net_usd_cents": amount,
        }

    def _guard_revision(self, state, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise DemoError("expected_revision must be a nonnegative integer")
        if expected_revision != state["revision"]:
            raise DemoError("This run has advanced. Use its current revision.", 409, self._snapshot(state))

    def advance(self, run_id, expected_revision):
        with self.lock, connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, run_id)
            self._guard_revision(state, expected_revision)
            if state["terminal"] or not state["can_advance"]:
                raise DemoError("This run cannot advance in its current state.", 409, self._snapshot(state, db))
            state["revision"] += 1
            if state["scenario"] == "historical_agent_error":
                self._advance_historical(db, state)
            else:
                self._advance_standard(db, state)
            db.execute("UPDATE runs SET state_json=? WHERE id=?", (encode(state), run_id))
            return self._snapshot(state, db)

    def verify(self, run_id, expected_revision):
        with self.lock, connect(self.path) as db:
            state = self._read(db, run_id)
            self._guard_revision(state, expected_revision)
            raise DemoError("This USDC-to-USD flow has no bank-verification step.", 409, self._snapshot(state, db))

    def _advance_standard(self, db, state):
        step = state["step"] + 1
        scenario = state["scenario"]
        if step in (3, 4, 5) and self._expire_before_dispatch(db, state, step):
            return
        if step in (4, 5):
            decision = evaluate(
                state["grant"], state["offer"], state["fx_quote"], int(time.time())
            )
            decision = self._bind_decision_to_admission(db, state, decision)
            if not decision.allowed:
                self._reject_changed_or_expired_terms(db, state, step, decision)
                return
            if step == 5:
                decision = self._authorization_decision(state, decision)
                if not decision.allowed:
                    self._reject_changed_or_expired_terms(db, state, step, decision)
                    return
        if step == 1:
            quantity = 3 if scenario == "quantity_violation" else 2
            state["offer"] = self._offer(quantity)
            state["user_message"] = (
                "The shopping agent proposed three tickets. Belay will check that against your two-ticket grant."
                if quantity == 3 else "I found two adjacent tickets for $200 total, including demo fees."
            )
            self._event(
                state, step=1, stage="offer_found", title="Shopping agent proposes an exact offer",
                explanation="The model can search and propose. It cannot approve its own proposal or touch the treasury.",
                actor="Shopping agent", sender="Shopping agent", recipient="Belay orchestrator",
                method="POST", url="https://merchant.belay.invalid/a2a/offers",
                request={"mission": state["mission"]}, response={"offer": state["offer"]},
            )
        elif step == 2:
            state["fx_quote"] = self._quote(state["operation_id"], state["offer"]["quantity"])
            state["conversion_state"] = "quoted"
            state["user_message"] = "Northstar wants dollars. The settlement adapter quoted USDC in and USD out."
            self._event(
                state, step=2, stage="checkout_bound", title="Checkout and conversion quote are bound",
                explanation="One identity binds the order, exact amount, USDC source and merchant USD beneficiary.",
                actor="Settlement adapter", sender="Belay", recipient="Conversion provider",
                method="POST", url="https://fx.belay.invalid/v1/quotes",
                request={"offer": state["offer"], "operation_id": state["operation_id"]},
                response={"quote": state["fx_quote"]},
            )
        elif step == 3:
            decision = evaluate(
                state["grant"], state["offer"], state["fx_quote"], int(time.time())
            )
            state["policy_decision"] = {"allowed": decision.allowed, "checks": decision.checks, "reason": decision.reason}
            if not decision.allowed:
                state.update(
                    terminal=True, can_advance=False, funding_state="funded_grant",
                    protection_state="not_reserved", order_state="blocked",
                    payout_state="not_started",
                    user_message=f"Blocked before funds moved. {decision.reason}",
                    outcome={"kind": "blocked", "headline": "Stopped before money moved", "detail": decision.reason},
                )
                self._event(
                    state, step=3, stage="policy_blocked", title="Deterministic policy blocks the proposal",
                    explanation="A configured grant, offer, or quote check failed before any hold, coverage reservation, or provider request.",
                    actor="Policy checker", sender="Belay policy", recipient="Belay executor",
                    method="DECIDE", url="belay://policy/admit", status=422,
                    request={"grant": state["grant"], "offer": state["offer"], "quote": state["fx_quote"]},
                    response=state["policy_decision"],
                )
                return
            amount = state["fx_quote"]["source_usdc_units"]
            self._move(db, state, f"{state['order_id']}:hold", "customer_available", "order_hold", "USDC", amount, "order_hold")
            self._reserve_coverage(db, state)
            state.update(
                funding_state="held", protection_state="committed",
                admission={
                    "operation_id": state["operation_id"],
                    "grant_digest": digest(state["grant"]),
                    "offer_digest": digest(state["offer"]),
                    "quote_digest": digest(state["fx_quote"]),
                    "source_usdc_units": amount,
                    "beneficiary_id": state["fx_quote"]["beneficiary_id"],
                    "coverage_usdc_units": COVERAGE_MAX_UNITS,
                },
            )
            self._record_order_authority(db, state, "admitted_order")
            state["user_message"] = "Every field matched. Belay held 200 USDC and committed up to 300 USDC of protection atomically."
            self._event(
                state, step=3, stage="admitted", title="Policy and reserve admit the order atomically",
                explanation="If either the rule check or reserve capacity fails, neither the customer hold nor protection commitment exists.",
                actor="Admission controller", sender="Policy + treasury", recipient="Belay executor",
                method="TRANSACT", url="belay://treasury/admit",
                request={"checks": list(decision.checks), "coverage_usdc_units": COVERAGE_MAX_UNITS},
                response={"admitted": True, "held_usdc_units": amount, "coverage_committed_usdc_units": COVERAGE_MAX_UNITS},
            )
        elif step == 4:
            intent = self._intent(state)
            state["intent"] = intent
            state["authorization"] = {
                "algorithm": "Ed25519-demo-marker", "key_reference": "demo:keyref:customer:7f4a",
                "intent_digest": digest(intent),
                "signature": "mocksig:transaction-bound:" + digest(intent)[-16:],
            }
            state["user_message"] = "The executor created one immutable instruction for this order and this merchant."
            self._event(
                state, step=4, stage="intent_signed", title="Exact settlement intent is authorized",
                explanation="The signature marker covers the grant, offer, quote, amount and beneficiary. It cannot be reused for another checkout.",
                actor="Protected signer", sender="Belay authority", recipient="Belay executor",
                method="SIGN", url="belay://signer/intent", request=intent,
                response=state["authorization"],
            )
        elif step == 5:
            if scenario == "cancel_before_dispatch":
                amount = state["fx_quote"]["source_usdc_units"]
                self._move(db, state, f"{state['order_id']}:cancel", "order_hold", "customer_available", "USDC", amount, "hold_released")
                self._release_coverage(db, state, "cancelled")
                state.update(
                    terminal=True, can_advance=False, funding_state="returned_before_dispatch",
                    protection_state="released", order_state="cancelled",
                    user_message="Cancelled before dispatch. All of your USDC is available again.",
                    outcome={"kind": "safe", "headline": "Cancelled with no payout", "detail": "The 200 USDC hold returned and the 300 USDC coverage commitment was released."},
                )
                self._event(
                    state, step=5, stage="cancelled", title="Held funds return before dispatch",
                    explanation="This is a true release: the merchant was never paid and no recovery claim is needed.",
                    actor="Treasury executor", sender="Order hold", recipient="Customer available balance",
                    method="TRANSFER", url="belay://treasury/release",
                    request={"reason": "customer_cancelled_before_dispatch"}, response={"returned_usdc_units": amount},
                )
                return
            amount = state["fx_quote"]["source_usdc_units"]
            self._move(db, state, f"{state['order_id']}:dispatch", "order_hold", "provider_in_transit", "USDC", amount, "provider_dispatch")
            try:
                provider = self.provider.submit(state["intent"])
            except ProviderConflict as exc:
                raise DemoError(str(exc), 409) from exc
            state.update(funding_state="dispatched", payout_state="provider_received")
            state["user_message"] = "200 USDC left the hold once, under the saved operation ID."
            self._event(
                state, step=5, stage="usdc_dispatched", title="Executor dispatches USDC once",
                explanation="The provider operation is idempotent. A retry with the same identity returns the prior operation.",
                actor="Treasury executor", sender="Belay order hold", recipient="Conversion provider",
                method="POST", url="https://fx.belay.invalid/v1/payouts", request=state["intent"],
                response={"provider_reference": provider["provider_reference"], "attempt_count": provider["attempt_count"]},
            )
        elif step == 6:
            try:
                provider = self.provider.convert(state["operation_id"])
            except ProviderConflict as exc:
                raise DemoError(str(exc), 409) from exc
            state["conversion_state"] = "converted"
            state["user_message"] = "The fictional provider converted 200 USDC to $200 USD."
            self._event(
                state, step=6, stage="converted", title="USDC is converted to USD",
                explanation="The merchant never handles crypto. A licensed production provider would perform conversion and compliance checks.",
                actor="Conversion provider", sender="USDC settlement account", recipient="USD payout account",
                method="CONVERT", url="https://fx.belay.invalid/v1/conversions",
                request={"operation_id": state["operation_id"], "source_usdc_units": provider["source_usdc_units"]},
                response={"conversion_state": provider["conversion_state"], "net_usd_cents": provider["net_usd_cents"]},
            )
        elif step == 7:
            state["payout_state"] = "submitted"
            state["user_message"] = "The USD payout is now addressed to Northstar's fictional bank account."
            self._event(
                state, step=7, stage="payout_submitted", title="USD payout is submitted to the merchant",
                explanation="Belay passes only the bound beneficiary and amount. This demo does not connect to a bank rail.",
                actor="Payout adapter", sender="Conversion provider", recipient=SELLER,
                method="POST", url="https://bankrail.belay.invalid/v1/payouts",
                request={"operation_id": state["operation_id"], "beneficiary_id": SELLER_ID, "net_usd_cents": state["offer"]["total_usd_cents"]},
                response={"accepted": True, "state": "processing"},
            )
        elif step == 8:
            try:
                provider = self.provider.complete(state["operation_id"])
            except ProviderConflict as exc:
                raise DemoError(str(exc), 409) from exc
            if scenario == "payout_reply_lost":
                state.update(payout_state="unknown", order_state="awaiting_payout_confirmation")
                state["user_message"] = "The reply disappeared. Belay shows unknown and will not send a second payout."
                state["outcome"] = {"kind": "warning", "headline": "Payout outcome unknown", "detail": "Provider truth exists under the original operation ID; next step performs a read-only lookup."}
                self._event(
                    state, step=8, stage="payout_unknown", title="Payout succeeds but the response is lost",
                    explanation="The provider has paid $200 once. Belay keeps its own state unknown instead of guessing or retrying with a new identity.",
                    actor="Fault injector", sender="Conversion provider", recipient="Belay payout adapter",
                    method="POST", url="https://fx.belay.invalid/v1/payouts/complete", status=504,
                    request={"operation_id": state["operation_id"]},
                    response={"simulated_transport_error": "response_lost_after_commit", "provider_reference": provider["provider_reference"]},
                )
                return
            self._confirm_payout(db, state, provider)
            self._event(
                state, step=8, stage="merchant_paid", title="Merchant receives $200 USD",
                explanation="The customer funded USDC; the merchant sees an ordinary USD payout. Payment still does not prove ticket delivery.",
                actor="Payout provider", sender="USD payout account", recipient=SELLER,
                method="WEBHOOK", url="https://belay.invalid/webhooks/payouts",
                request={"provider_reference": provider["provider_reference"]},
                response={"payout_state": "paid", "net_usd_cents": provider["net_usd_cents"]},
            )
        elif step == 9:
            if state["payout_state"] == "unknown":
                provider = self.provider.lookup(state["operation_id"])
                if not provider or provider["payout_state"] != "paid":
                    raise DemoError("Exact provider payout is not yet final", 409)
                self._confirm_payout(db, state, provider)
                state["user_message"] = "Belay found the original paid operation. Exactly one merchant payout exists."
                self._event(
                    state, step=9, stage="payout_reconciled", title="Read-only lookup reconciles the exact payout",
                    explanation="The lookup cannot create money. It confirms the saved operation and prevents a duplicate USD payout.",
                    actor="Recovery worker", sender="Belay", recipient="Conversion provider",
                    method="GET", url=f"https://fx.belay.invalid/v1/payouts/{state['operation_id']}",
                    request={"operation_id": state["operation_id"], "creates_payment": False},
                    response={"payout_state": provider["payout_state"], "attempt_count": provider["attempt_count"], "provider_reference": provider["provider_reference"]},
                )
            else:
                state["order_state"] = "merchant_confirmed"
                state["user_message"] = "Northstar accepted the paid order and issued a merchant order reference."
                self._event(
                    state, step=9, stage="order_confirmed", title="Merchant confirms the ticket order",
                    explanation="Order acceptance is recorded separately from payment and separately from delivery.",
                    actor="Merchant endpoint", sender=SELLER, recipient="Belay orchestrator",
                    method="A2A", url="https://merchant.belay.invalid/a2a/orders/status",
                    request={"operation_id": state["operation_id"]},
                    response={"order_id": state["order_id"], "order_state": "confirmed"},
                )
        elif step == 10:
            if state["order_state"] != "merchant_confirmed":
                state["order_state"] = "merchant_confirmed"
                title = "Merchant order is linked after payout recovery"
                explanation = "The recovered payout and merchant order share the original operation identity."
            else:
                title = "Belay asks for delivery evidence"
                explanation = "A paid order is not treated as fulfilled until ticket evidence matches the exact order."
            state["user_message"] = "Payment is settled. Belay now checks the actual ticket delivery."
            self._event(
                state, step=10, stage="delivery_check", title=title, explanation=explanation,
                actor="Outcome verifier", sender="Belay", recipient="Merchant delivery endpoint",
                method="GET", url="https://merchant.belay.invalid/a2a/orders/delivery",
                request={"order_id": state["order_id"], "expected_quantity": 2},
                response={"check_started": True},
            )
        elif step == 11:
            self._delivery_decision(db, state, scenario)
        elif step == 12:
            if scenario == "non_delivery_paid":
                self._approve_claim(db, state)
                state.update(protection_state="claim_approved")
                state["user_message"] = "The claims service approved 200 USDC. It did not ask the shopping agent to judge itself."
                self._event(
                    state, step=12, stage="claim_approved", title="Independent controls approve the real loss",
                    explanation="Coverage shifts from committed to pending. Reserve cash has not moved yet.",
                    actor="Claims service", sender="Evidence adjudicator", recipient="Protection treasury",
                    method="DECIDE", url="belay://claims/adjudicate",
                    request={"case_id": state["case_id"], "economic_loss": "paid_order_not_delivered"},
                    response={"approved_usdc_units": 200 * USDC_SCALE, "executor": "separate_from_shopping_agent"},
                )
            else:
                self._complete_success(db, state)
        elif step == 13 and scenario == "non_delivery_paid":
            paid_units = self._pay_claim(db, state)
            self._release_coverage(db, state)
            state.update(
                terminal=True, can_advance=False, protection_state="paid",
                recovery_state="supplier_recovery_open",
                outcome={"kind": "remedied", "headline": "Customer restored: 200 USDC", "detail": "Reserve: 800 USDC · Merchant still has $200 · Supplier recovery handoff is outside this demo"},
            )
            state["receipt"] = self._receipt(db, state, remedy=paid_units)
            state["user_message"] = "200 USDC is available again now. Belay pursues the supplier separately."
            self._event(
                state, step=13, stage="customer_restored", title="Protection reserve restores the customer",
                explanation="The claim pays once from the reserve. It does not pretend the merchant payment was reversed.",
                actor="Protection treasury", sender="Belay protection reserve", recipient="Customer available balance",
                method="TRANSFER", url="belay://treasury/protection-payout",
                request={"case_id": state["case_id"], "approved_usdc_units": paid_units},
                response={"paid_usdc_units": paid_units, "supplier_recovery": "open", "merchant_usd_reversed": False},
            )
        else:
            raise DemoError("No transition is defined for this run", 409)

    def _confirm_payout(self, db, state, provider):
        self._validate_provider_payout(state, provider)
        self._record_conversion(db, state, provider)
        state["payout_evidence"] = {
            "provider_reference": provider["provider_reference"],
            "operation_id": provider["operation_id"],
            "net_usd_cents": provider["net_usd_cents"],
            "payout_state": provider["payout_state"],
        }
        state.update(funding_state="settled", conversion_state="converted", payout_state="paid")
        state["user_message"] = f"{SELLER} received $200 USD. Delivery is still a separate question."

    def _validate_provider_payout(self, state, provider):
        expected = {
            "operation_id": state["operation_id"],
            "intent_json": encode(state["intent"]),
            "beneficiary_id": state["fx_quote"]["beneficiary_id"],
            "source_usdc_units": state["fx_quote"]["source_usdc_units"],
            "net_usd_cents": state["fx_quote"]["merchant_net_usd_cents"],
            "funding_state": "settled",
            "conversion_state": "converted",
            "payout_state": "paid",
        }
        mismatched = [
            field
            for field, value in expected.items()
            if provider is None or provider.get(field) != value
        ]
        if mismatched:
            raise DemoError(
                "Provider payout failed exact settlement validation: "
                + ", ".join(mismatched),
                409,
            )

    def _expire_before_dispatch(self, db, state, step):
        if time.time() < state["grant"]["expires_at"]:
            return False
        held = self._account(db, state["id"], "order_hold", "USDC")
        if held:
            self._move(
                db, state, f"{state['order_id']}:expired-release", "order_hold",
                "customer_available", "USDC", held, "expired_hold_released",
            )
        if self._coverage(db, state)["max_units"]:
            self._release_coverage(db, state, "expired")
        state.update(
            terminal=True, can_advance=False,
            funding_state="returned_after_expiry" if held else "funded_grant",
            order_state="expired", protection_state="released" if held else "not_reserved",
            user_message="The 30-minute grant expired before dispatch. No merchant payout was sent.",
            outcome={
                "kind": "safe", "headline": "Grant expired safely",
                "detail": "Any local hold returned to the customer before USDC left Belay.",
            },
        )
        self._event(
            state, step=step, stage="grant_expired", title="Expired grant stops execution",
            explanation="Belay rechecks time-bound authority before admission, signing and dispatch.",
            actor="Authority service", sender="Grant validator", recipient="Belay executor",
            method="EXPIRE", url="belay://authority/grants/check", status=410,
            request={"grant_expires_at": state["grant"]["expires_at"], "gate_step": step},
            response={"merchant_payout_sent": False, "returned_usdc_units": held},
        )
        return True

    def _reject_changed_or_expired_terms(self, db, state, step, decision):
        held = self._account(db, state["id"], "order_hold", "USDC")
        if held:
            self._move(
                db, state, f"{state['order_id']}:terms-rejected", "order_hold",
                "customer_available", "USDC", held, "rejected_hold_released",
            )
        coverage = self._coverage(db, state)
        if coverage["max_units"]:
            self._release_coverage(db, state, "terms_rejected")
        state.update(
            terminal=True, can_advance=False, policy_decision={
                "allowed": False, "checks": decision.checks, "reason": decision.reason,
            },
            funding_state="returned_after_rejection" if held else "funded_grant",
            order_state="terms_rejected",
            protection_state="released" if coverage["max_units"] else "not_reserved",
            user_message="The quote, order, or signed intent is no longer valid. Belay stopped before merchant dispatch and returned any hold.",
            outcome={
                "kind": "safe", "headline": "Changed terms stopped safely",
                "detail": decision.reason,
            },
        )
        self._event(
            state, step=step, stage="terms_rejected",
            title="Admission is rechecked before dispatch",
            explanation="A previous approval cannot authorize an expired quote, changed transaction, or altered signed intent.",
            actor="Policy checker", sender="Belay policy", recipient="Belay executor",
            method="DECIDE", url="belay://policy/revalidate", status=422,
            request={
                "gate_step": step, "offer": state["offer"],
                "quote": state["fx_quote"], "admission": state.get("admission"),
            },
            response=state["policy_decision"],
        )

    def _bind_decision_to_admission(self, db, state, decision):
        admission = state.get("admission") or {}
        coverage = self._coverage(db, state)
        authority = db.execute(
            "SELECT * FROM order_authority_v3 WHERE run_id=?",
            (state["id"],),
        ).fetchone()
        authority_fields = (
            "run_id", "order_id", "operation_id", "record_type", "grant_json",
            "offer_json", "quote_json", "grant_digest", "offer_digest",
            "quote_digest", "source_usdc_units", "beneficiary_id",
        )
        exact_authority = authority is not None and tuple(
            authority[field] for field in authority_fields
        ) == self._authority_values(state, "admitted_order")
        expected = {
            "operation_id": state["operation_id"],
            "grant_digest": digest(state["grant"]),
            "offer_digest": digest(state["offer"]),
            "quote_digest": digest(state["fx_quote"]),
            "source_usdc_units": state["fx_quote"]["source_usdc_units"],
            "beneficiary_id": state["fx_quote"]["beneficiary_id"],
            "coverage_usdc_units": COVERAGE_MAX_UNITS,
        }
        exact_snapshot = admission == expected
        exact_hold = (
            self._account(db, state["id"], "order_hold", "USDC")
            == admission.get("source_usdc_units")
        )
        exact_coverage = (
            coverage["committed_units"] == admission.get("coverage_usdc_units")
            and coverage["pending_units"] == 0
            and coverage["paid_units"] == 0
        )
        binding_check = {
            "name": "admitted_transaction_binding",
            "expected": admission,
            "observed": {
                "transaction": expected,
                "held_usdc_units": self._account(
                    db, state["id"], "order_hold", "USDC"
                ),
                "coverage_committed_usdc_units": coverage["committed_units"],
            },
            "passed": exact_authority and exact_snapshot and exact_hold and exact_coverage,
        }
        checks = (*decision.checks, binding_check)
        if not decision.allowed:
            return PolicyDecision(False, checks, decision.reason)
        if not binding_check["passed"]:
            return PolicyDecision(
                False,
                checks,
                "Blocked: the transaction no longer matches the exact admitted hold.",
            )
        return PolicyDecision(True, checks, decision.reason)

    def _authorization_decision(self, state, decision):
        expected_intent = self._intent(state)
        expected_digest = digest(expected_intent)
        authorization = state.get("authorization") or {}
        checks = (
            *decision.checks,
            {
                "name": "exact_signed_intent",
                "expected": expected_intent,
                "observed": state.get("intent"),
                "passed": state.get("intent") == expected_intent,
            },
            {
                "name": "intent_digest_binding",
                "expected": expected_digest,
                "observed": authorization.get("intent_digest"),
                "passed": authorization.get("intent_digest") == expected_digest,
            },
            {
                "name": "demo_signature_marker",
                "expected": "mocksig:transaction-bound:" + expected_digest[-16:],
                "observed": authorization.get("signature"),
                "passed": authorization.get("signature")
                == "mocksig:transaction-bound:" + expected_digest[-16:],
            },
            {
                "name": "protected_key_reference",
                "expected": "demo:keyref:customer:7f4a",
                "observed": authorization.get("key_reference"),
                "passed": authorization.get("key_reference")
                == "demo:keyref:customer:7f4a",
            },
        )
        if not all(check["passed"] for check in checks):
            return PolicyDecision(
                False, checks, "Blocked: the signed settlement intent failed exact validation."
            )
        return PolicyDecision(True, checks, decision.reason)

    def _delivery_decision(self, db, state, scenario):
        if scenario == "non_delivery_paid":
            state.update(delivery_state="not_delivered", protection_state="claim_open", recovery_state="supplier_recovery_open")
            self._record_delivery_outcome(db, state)
            self._open_claim(db, state, "supplier_non_delivery", 200 * USDC_SCALE, {"merchant_paid_usd_cents": 20_000, "tickets_received": 0})
            state["user_message"] = "No tickets arrived. Belay opened an independent 200 USDC non-delivery claim."
            state["outcome"] = {"kind": "warning", "headline": "Merchant paid; delivery failed", "detail": "The original payment cannot be pulled back. Protection is evaluated separately."}
            self._event(
                state, step=11, stage="non_delivery", title="Delivery evidence shows zero tickets",
                explanation="The merchant remains paid. An independent claims service opens a case for the customer's actual $200 loss.",
                actor="Outcome verifier", sender="Evidence service", recipient="Claims service",
                method="POST", url="belay://claims/cases",
                request={"order_id": state["order_id"], "tickets_received": 0},
                response={"case_id": state["case_id"], "loss_type": "supplier_non_delivery", "requested_usdc_units": 200 * USDC_SCALE},
            )
        elif scenario == "evidence_conflict":
            state.update(
                delivery_state="evidence_conflict", protection_state="review_required",
                recovery_state="manual_review", manual_review=True, terminal=True,
                can_advance=False, user_message="One source says delivered and another says missing. Belay paused without paying a claim.",
                outcome={"kind": "review", "headline": "Human review required", "detail": "No automatic reserve payment. The operator resolution flow is outside this demo."},
            )
            self._record_delivery_outcome(db, state)
            self._open_claim(db, state, "ambiguous_delivery", 200 * USDC_SCALE, {"merchant": "delivered", "wallet": "missing"})
            db.execute(
                "UPDATE coverage_v3 SET status='review_required' WHERE run_id=? AND order_id=?",
                (state["id"], state["order_id"]),
            )
            self._event(
                state, step=11, stage="review_required", title="Conflicting evidence stops automation",
                explanation="Belay abstains when the facts do not support a safe automated decision.",
                actor="Evidence adjudicator", sender="Evidence service", recipient="Human review queue",
                method="DECIDE", url="belay://claims/adjudicate", status=409,
                request={"merchant_status": "delivered", "customer_wallet_status": "missing"},
                response={"decision": "abstain", "paid_usdc_units": 0},
            )
        else:
            state["tickets"] = [
                {"section": "102", "row": "H", "seat": "12", "holder": "Alex Morgan"},
                {"section": "102", "row": "H", "seat": "13", "holder": "Alex Morgan"},
            ]
            state.update(delivery_state="verified", order_state="fulfilled", protection_state="ready_to_close")
            self._record_delivery_outcome(db, state)
            state["user_message"] = "Two matching tickets arrived. Payment and delivery are now recorded independently."
            self._event(
                state, step=11, stage="delivered", title="Two tickets are verified",
                explanation="The outcome receipt matches the event, order and exact quantity before coverage is released.",
                actor="Outcome verifier", sender="Ticket wallet", recipient="Belay evidence service",
                method="VERIFY", url="belay://evidence/tickets",
                request={"order_id": state["order_id"], "expected_quantity": 2},
                response={"verified": True, "tickets": state["tickets"]},
            )

    def _complete_success(self, db, state):
        self._release_coverage(db, state)
        state.update(
            terminal=True, can_advance=False, protection_state="released",
            outcome={"kind": "success", "headline": "Purchase delivered", "detail": "2 tickets · 200 USDC funded · $200 USD paid · 0 claims"},
        )
        state["receipt"] = self._receipt(db, state, remedy=0)
        state["user_message"] = "Done. Your linked receipt records the instruction, purchase, payout and delivery."
        self._event(
            state, step=12, stage="complete", title="Unified receipt closes the protected purchase",
            explanation="Unused protection capacity is released only after verified delivery.",
            actor="Receipt service", sender="Belay", recipient="Customer",
            method="ISSUE", url="belay://receipts/unified",
            request={"order_id": state["order_id"]}, response=state["receipt"],
        )

    def _advance_historical(self, db, state):
        step = state["step"] + 1
        if step == 1:
            state["user_message"] = "The audit compared the signed two-ticket grant with a three-ticket receipt."
            self._event(
                state, step=1, stage="agent_error_detected", title="Receipt exposes a one-ticket agent error",
                explanation="This is imported post-payment evidence. The current executor still blocks this proposal in the live scenario.",
                actor="Audit worker", sender="Receipt store", recipient="Evidence service",
                method="VERIFY", url="belay://evidence/compare",
                request={"authorized_quantity": 2, "purchased_quantity": 3},
                response={
                    "mismatch": 1,
                    "unauthorized_charge_usdc_units": 100 * USDC_SCALE,
                    "extra_ticket_disposition": state["unauthorized_item"],
                },
            )
        elif step == 2:
            self._open_claim(db, state, "agent_quantity_error", 100 * USDC_SCALE, {"grant_quantity": 2, "receipt_quantity": 3})
            state.update(protection_state="claim_open")
            state["user_message"] = "Belay opened a contractual remedy only for the unauthorized ticket charge: 100 USDC."
            self._event(
                state, step=2, stage="agent_error_claim", title="Unauthorized agent charge is isolated",
                explanation="The two intended tickets remain valid. The extra ticket is quarantined for return or resale instead of being delivered as free value.",
                actor="Claims intake", sender="Evidence service", recipient="Claims service",
                method="POST", url="belay://claims/cases",
                request={
                    "loss_type": "agent_quantity_error", "ordered": 2,
                    "purchased": 3, "extra_ticket_disposition": state["unauthorized_item"],
                },
                response={"case_id": state["case_id"], "requested_usdc_units": 100 * USDC_SCALE},
            )
        elif step == 3:
            self._approve_claim(db, state)
            state.update(protection_state="claim_approved")
            state["user_message"] = "Independent controls approved the bounded 100 USDC agent-error remedy."
            self._event(
                state, step=3, stage="claim_approved", title="Agent-error cover approves 100 USDC",
                explanation="The payout is bounded by the order's combined 300 USDC coverage and the unauthorized charge defined in the demo terms.",
                actor="Claims service", sender="Evidence adjudicator", recipient="Protection treasury",
                method="DECIDE", url="belay://claims/adjudicate",
                request={"case_id": state["case_id"], "covered_event": "one_unauthorized_ticket_charge"},
                response={"approved_usdc_units": 100 * USDC_SCALE},
            )
        elif step == 4:
            paid_units = self._pay_claim(db, state)
            state.update(protection_state="claim_paid")
            state["user_message"] = "100 USDC returned to the customer. The merchant keeps the valid $300 sale; Belay absorbs the agent error."
            self._event(
                state, step=4, stage="customer_restored", title="Reserve pays the agent-error remedy once",
                explanation="The remedy creates immediate customer liquidity while Belay bears the return-or-resale risk for the quarantined ticket.",
                actor="Protection treasury", sender="Belay protection reserve", recipient="Customer available balance",
                method="TRANSFER", url="belay://treasury/protection-payout",
                request={"case_id": state["case_id"]},
                response={"paid_usdc_units": paid_units, "merchant_usd_reversed": False},
            )
        elif step == 5:
            claim = db.execute(
                "SELECT status,approved_units,paid_units FROM claims_v3 WHERE case_id=?",
                (state["case_id"],),
            ).fetchone()
            if (
                claim is None
                or claim["status"] != "paid"
                or int(claim["approved_units"]) != int(claim["paid_units"])
            ):
                raise DemoError("Paid claim record is not internally consistent", 409)
            paid_units = int(claim["paid_units"])
            state["claim_amount_usdc_units"] = paid_units
            self._release_coverage(db, state)
            state.update(
                terminal=True, can_advance=False, protection_state="paid",
                recovery_state="belay_agent_error_absorbed",
                outcome={"kind": "remedied", "headline": "Agent error covered: 100 USDC", "detail": "Customer keeps 2 intended tickets · Extra ticket quarantined · Reserve: 900 USDC"},
            )
            state["receipt"] = self._receipt(db, state, remedy=paid_units)
            state["user_message"] = "Done. The receipt separates the intended purchase from the extra-ticket remedy."
            self._event(
                state, step=5, stage="complete", title="Receipt closes the customer remedy",
                explanation="The injected fault, payment, ticket disposition and bounded remedy remain independently visible.",
                actor="Receipt service", sender="Belay", recipient="Customer",
                method="ISSUE", url="belay://receipts/unified",
                request={"order_id": state["order_id"]}, response=state["receipt"],
            )
        else:
            raise DemoError("No transition is defined for this run", 409)

    def _receipt(self, db, state, remedy):
        record_type = (
            "historical_import"
            if state["entry_mode"] == "injected_historical_fixture"
            else "admitted_order"
        )
        authority = db.execute(
            "SELECT * FROM order_authority_v3 WHERE run_id=?",
            (state["id"],),
        ).fetchone()
        authority_fields = (
            "run_id", "order_id", "operation_id", "record_type", "grant_json",
            "offer_json", "quote_json", "grant_digest", "offer_digest",
            "quote_digest", "source_usdc_units", "beneficiary_id",
        )
        if authority is None or tuple(
            authority[field] for field in authority_fields
        ) != self._authority_values(state, record_type):
            raise DemoError(
                "Current order data does not match the persisted authority record", 409
            )

        provider = self.provider.lookup(state["operation_id"])
        self._validate_provider_payout(state, provider)
        settlement = db.execute(
            "SELECT * FROM settlements_v3 WHERE operation_id=?",
            (state["operation_id"],),
        ).fetchone()
        settlement_fields = (
            "operation_id", "run_id", "order_id", "intent_digest",
            "provider_reference", "beneficiary_id", "source_asset",
            "source_units", "destination_asset", "net_destination_units",
            "payout_state",
        )
        if settlement is None or tuple(
            settlement[field] for field in settlement_fields
        ) != self._settlement_values(state, provider):
            raise DemoError(
                "Current payout data does not match the persisted settlement record", 409
            )
        if self._account(db, state["id"], "merchant_received", "USD_CENTS") != int(
            settlement["net_destination_units"]
        ):
            raise DemoError("Merchant balance does not match settlement", 409)

        delivery = db.execute(
            "SELECT * FROM delivery_outcomes_v3 WHERE run_id=?",
            (state["id"],),
        ).fetchone()
        delivery_fields = (
            "run_id", "order_id", "delivery_state", "evidence_json",
            "evidence_digest",
        )
        if delivery is None or tuple(
            delivery[field] for field in delivery_fields
        ) != self._delivery_values(state):
            raise DemoError(
                "Current delivery data does not match the persisted evidence record", 409
            )

        grant = json.loads(authority["grant_json"])
        offer = json.loads(authority["offer_json"])
        return {
            "receipt_id": "rcpt_" + state["id"][:20],
            "instruction": {
                "quantity": grant["quantity"],
                "maximum_usdc_units": grant["max_total_usdc_units"],
                "grant_digest": authority["grant_digest"],
            },
            "purchase": {
                "order_id": authority["order_id"], "quantity": offer["quantity"],
                "merchant": SELLER, "total_usd_cents": offer["total_usd_cents"],
            },
            "payment": {
                "operation_id": settlement["operation_id"],
                "source_asset": settlement["source_asset"],
                "merchant_asset": settlement["destination_asset"],
                "merchant_received_usd_cents": settlement["net_destination_units"],
                "provider_reference": settlement["provider_reference"],
            },
            "outcome": {
                "delivery_state": delivery["delivery_state"],
                "remedy_usdc_units": remedy, "recovery_state": state["recovery_state"],
            },
        }
