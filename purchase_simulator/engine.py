"""Persisted purchase walkthrough with an independent, entirely local provider.

Only the browser-to-server HTTP connection is real. Merchant, credential,
processor and issuer calls are ordinary local functions. No network client or
real key material is used. Signature markers are illustrative, not cryptography.
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

EVENT = "The Midnight Signals"
DATE = "2026-10-24"
VENUE = "Harbor Hall, Boston"
SELLER = "Northstar Tickets"
SEATS = ["102-H-12", "102-H-13"]
NOTICE = (
    "Local simulation. All money, providers and credentials are fictional. "
    "mocksig markers are not cryptographic signatures. The example payloads "
    "are illustrative, not an AP2 implementation. No external API is called."
)
SCENARIOS = [
    {"id": "success", "label": "Everything works", "description": "Two tickets for $280 total, bought within the initial mission's spending authority."},
    {"id": "lost_reply", "label": "Payment succeeds; reply is lost", "description": "The provider captures $280, but Belay must retrieve the original order before reporting success."},
    {"id": "price_change", "label": "The final price changes", "description": "The checkout total rises from $280 to $320; the original budget is enforced before credentials or payment."},
    {"id": "bank_verification", "label": "The bank needs verification", "description": "The simulated issuer requires an extra verification step before authorizing the payment."},
    {"id": "declined", "label": "The bank declines", "description": "The issuer rejects authorization; no money is captured and the reservation is released."},
]
CREDENTIALS = [
    {"name": "Protected signing-key reference", "key": "demo_keyref_belay_agent", "holder": "Belay protected signer", "purpose": "A fictional reference, not private key material. The planner never receives a private key."},
    {"name": "Delegation marker", "key": "mocksig:user-grant:approved", "holder": "Belay authority service", "purpose": "Illustrates the initial user's delegation. No cryptographic verification is performed."},
    {"name": "Restricted payment token", "key": "demo_spt_<operation_id>", "holder": "Merchant checkout", "purpose": "A fake token tied to this seller, operation and exact total; it is issued at step 5."},
    {"name": "Processor API credential", "key": "demo_processor_key_NOT_REAL", "holder": "Merchant backend", "purpose": "Illustrates a merchant authenticating to its payment processor; it cannot connect to a real service."},
    {"name": "Merchant API credential", "key": "demo_merchant_access_NOT_REAL", "holder": "Belay executor", "purpose": "A fictional access marker used when submitting this demo checkout; it cannot authenticate to a real merchant."},
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
    db.execute("PRAGMA synchronous=FULL")
    try:
        with db:
            yield db
    finally:
        db.close()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Engine:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "app.sqlite3"
        self.provider_path = self.data_dir / "provider.sqlite3"
        self.lock = threading.RLock()
        with connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, state_json TEXT NOT NULL)")
        with connect(self.provider_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orders (
                operation_id TEXT PRIMARY KEY, intent_json TEXT NOT NULL,
                payment_status TEXT NOT NULL, order_status TEXT NOT NULL,
                delivery_status TEXT NOT NULL, captured_cents INTEGER NOT NULL,
                tickets_json TEXT NOT NULL)""")

    def close(self):
        """Connections are scoped to individual operations; no service remains running."""

    def config(self):
        return json.loads(encode({"scenarios": SCENARIOS, "credentials": CREDENTIALS, "notice": NOTICE}))

    def _read(self, db, run_id):
        if not isinstance(run_id, str):
            raise DemoError("Run not found", 404)
        row = db.execute("SELECT state_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DemoError("Run not found", 404)
        return json.loads(row["state_json"])

    def _snapshot(self, state):
        result = json.loads(encode(state))
        # Teaching-only observation. Recovery decisions use _provider_lookup
        # explicitly; this count never decides whether to submit or retry.
        row = self._provider_lookup(state["operation_id"])
        result["provider_charge_count"] = int(row is not None and row["captured_cents"] > 0)
        return result

    def get(self, run_id):
        with self.lock, connect(self.path) as db:
            return self._snapshot(self._read(db, run_id))

    def _event(self, state, *, step, stage, title, explanation, actor, sender,
               recipient, method, url, status=200, request=None, response=None):
        state.update(step=step, stage=stage, title=title, explanation=explanation)
        state["events"].append({
            "id": f"{state['id']}:{state['revision']}", "step": step,
            "title": title, "explanation": explanation, "actor": actor,
            "from": sender, "to": recipient, "method": method, "url": url,
            "status": status, "request": request or {}, "response": response or {},
        })

    def create(self, scenario, budget_cents, quantity=2):
        if not isinstance(scenario, str) or scenario not in {s["id"] for s in SCENARIOS}:
            raise DemoError("Choose a supported scenario")
        if type(budget_cents) is not int or not 1 <= budget_cents <= 1_000_000:
            raise DemoError("budget_cents must be an integer from 1 to 1000000")
        if type(quantity) is not int or quantity != 2:
            raise DemoError("This demonstration requires exactly two tickets")
        with self.lock, connect(self.path) as db:
            run_id = uuid.uuid4().hex
            operation = "purchase_" + uuid.uuid4().hex
            issued_at = int(time.time())
            mission = {"event": EVENT, "date": DATE, "time": "8:00 PM ET", "venue": VENUE,
                       "quantity": quantity, "budget_cents": budget_cents}
            state = {
                "id": run_id, "scenario": scenario, "revision": 0,
                "stage": "mission", "step": 0, "title": "", "explanation": "",
                "terminal": False, "needs_verification": False, "can_advance": True,
                "user_message": "Mission approved. Belay may buy exactly two adjacent seats within this total budget.",
                "mission": mission, "offer": None,
                "budget": {"reserved_cents": 0, "spent_cents": 0, "available_cents": budget_cents},
                "payment_status": "not_started", "order_status": "not_submitted",
                "delivery_status": "not_started", "operation_id": operation,
                "events": [], "tickets": [],
                "artifacts": {"checkout_id": None, "intent": None, "signature": None,
                              "checkout_binding": None, "checkout_authorization": None,
                              "payment_mandate": None, "payment_token": None,
                              "payment_id": None, "order_id": None},
                "grant": {"event": EVENT, "date": DATE, "venue": VENUE, "quantity": 2,
                          "adjacent": True, "seller": SELLER, "currency": "USD",
                          "max_total_cents": budget_cents, "approved": True,
                          "issued_at": issued_at, "expires_at": issued_at + 1800,
                          "signature": "mocksig:user-grant:approved"},
            }
            self._event(state, step=0, stage="mission", title="You approve the mission once",
                        explanation="This initial delegation allows the exact mission within its budget. It is not a payment, and no private key is handed to the agent.",
                        actor="User", sender="User", recipient="Belay", method="POST", url="/api/runs", status=201,
                        request={"scenario": scenario, "mission": mission},
                        response={"approved": True, "operation_id": operation, "signature": "mocksig:user-grant:approved"})
            db.execute("INSERT INTO runs VALUES(?,?)", (run_id, encode(state)))
            return self._snapshot(state)

    def _guard_revision(self, state, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise DemoError("expected_revision must be a nonnegative integer")
        if expected_revision != state["revision"]:
            raise DemoError("This run has advanced. Use its current revision.", 409, self._snapshot(state))

    def _grant_expired(self, state):
        return time.time() >= state["grant"]["expires_at"]

    def advance(self, run_id, expected_revision):
        with self.lock, connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, run_id)
            self._guard_revision(state, expected_revision)
            if state["terminal"] or state["needs_verification"]:
                raise DemoError("This run cannot advance in its current state.", 409, self._snapshot(state))
            state["revision"] += 1
            self._advance(state)
            db.execute("UPDATE runs SET state_json=? WHERE id=?", (encode(state), run_id))
            return self._snapshot(state)

    def verify(self, run_id, expected_revision):
        with self.lock, connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, run_id)
            self._guard_revision(state, expected_revision)
            if state["scenario"] != "bank_verification" or not state["needs_verification"] or state["step"] != 9:
                raise DemoError("No bank verification is waiting for this run.", 409, self._snapshot(state))
            if self._grant_expired(state):
                raise DemoError("The mission expired before bank verification. No new authorization was sent; the pending order's reservation remains. This demo has no renewal or cancellation route.", 409, self._snapshot(state))
            self._provider_authorize(state["operation_id"], "authorized")
            state.update(revision=state["revision"] + 1, needs_verification=False,
                         can_advance=True, payment_status="authorized",
                         user_message="Simulated bank verification completed. Payment is authorized; tickets are not confirmed yet.")
            self._event(state, step=9, stage="authorized", title="The bank verifies the customer",
                        explanation="This is a simulated issuer-required exception. It is separate from the mission's initial spending authority; authorization still is not capture or delivery.",
                        actor="Issuing bank", sender="User", recipient="Issuing bank", method="POST",
                        url="https://issuer.belay.invalid/v1/challenges/verify",
                        request={"operation_id": state["operation_id"], "demo_verification": "passed"},
                        response={"authorization": "approved", "captured_cents": 0})
            db.execute("UPDATE runs SET state_json=? WHERE id=?", (encode(state), run_id))
            return self._snapshot(state)

    def _provider_lookup(self, operation):
        with connect(self.provider_path) as db:
            row = db.execute("SELECT * FROM orders WHERE operation_id=?", (operation,)).fetchone()
            return dict(row) if row is not None else None

    def _provider_submit(self, intent):
        with connect(self.provider_path) as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT intent_json FROM orders WHERE operation_id=?", (intent["operation_id"],)).fetchone()
            if prior is not None:
                if prior["intent_json"] != encode(intent):
                    raise DemoError("The operation already belongs to a different exact purchase", 409)
                return
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
                       (intent["operation_id"], encode(intent), "processing", "pending", "pending", 0, "[]"))

    def _provider_authorize(self, operation, payment_status):
        with connect(self.provider_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payment_status FROM orders WHERE operation_id=?", (operation,)).fetchone()
            if row is None:
                raise DemoError("The original provider operation is missing", 409)
            if row["payment_status"] == "captured":
                return
            db.execute("UPDATE orders SET payment_status=? WHERE operation_id=?", (payment_status, operation))

    def _provider_capture(self, operation):
        # This transaction commits independently of the app state. A lost
        # response cannot undo the provider's recorded charge or order.
        with connect(self.provider_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orders WHERE operation_id=?", (operation,)).fetchone()
            if row is None or row["payment_status"] not in ("authorized", "captured"):
                raise DemoError("The provider has not authorized this operation", 409)
            if row["payment_status"] == "captured":
                return dict(row)
            intent = json.loads(row["intent_json"])
            # The fictional merchant independently fulfills its own inventory.
            tickets = [{"section": "102", "row": "H", "seat": seat, "event": EVENT,
                        "date": DATE, "time": "8:00 PM ET", "venue": VENUE} for seat in ("12", "13")]
            db.execute("UPDATE orders SET payment_status='captured',order_status='confirmed',"
                       "delivery_status='delivered',captured_cents=?,tickets_json=? WHERE operation_id=?",
                       (intent["amount_cents"], encode(tickets), operation))
            return dict(db.execute("SELECT * FROM orders WHERE operation_id=?", (operation,)).fetchone())

    def _record_receipt(self, state, receipt):
        expected = state["artifacts"]["intent"]
        try:
            tickets = json.loads(receipt["tickets_json"])
            received_seats = [f"{ticket['section']}-{ticket['row']}-{ticket['seat']}" for ticket in tickets]
            ticket_details_match = all(
                ticket["event"] == expected["event"] and ticket["date"] == expected["date"]
                and ticket["venue"] == expected["venue"] for ticket in tickets
            )
        except (ValueError, KeyError, TypeError):
            return False
        if (receipt["operation_id"] != state["operation_id"]
                or receipt["intent_json"] != encode(expected)
                or receipt["captured_cents"] != expected["amount_cents"]
                or receipt["payment_status"] != "captured"
                or receipt["order_status"] != "confirmed"
                or receipt["delivery_status"] != "delivered"
                or received_seats != expected["seat_ids"]
                or not ticket_details_match):
            return False
        state.update(payment_status="captured", order_status="confirmed",
                     delivery_status=receipt["delivery_status"], tickets=tickets)
        state["budget"] = {"reserved_cents": 0, "spent_cents": receipt["captured_cents"],
                           "available_cents": state["mission"]["budget_cents"] - receipt["captured_cents"]}
        state["artifacts"]["order_id"] = "ord_demo_" + state["operation_id"]
        return True

    def _advance(self, state):
        step = state["step"] + 1
        operation = state["operation_id"]
        artifacts = state["artifacts"]
        if state["step"] == 10 and state["payment_status"] == "capture_unknown":
            receipt = self._provider_lookup(operation)
            found = receipt is not None and self._record_receipt(state, receipt)
            if not found:
                state.update(terminal=True, can_advance=False,
                             user_message="The provider could not confirm this exact purchase. Its budget stays reserved; no second purchase was sent.")
            else:
                state["user_message"] = "The original order was found: one $280 payment and two tickets. No second payment was sent."
            self._event(state, step=10, stage="reconciled" if found else "unresolved",
                        title="Recover the original order" if found else "Keep the purchase unresolved",
                        explanation="Belay reads the exact saved operation at the merchant. Only matching order and payment evidence releases the reservation; the teaching charge counter does not authorize a retry.",
                        actor="Belay recovery", sender="Belay", recipient="Merchant", method="GET",
                        url=f"https://merchant.belay.invalid/v1/orders/by-operation/{operation}",
                        request={"operation_id": operation, "creates_payment": False},
                        response={"found": found, "order_id": artifacts["order_id"],
                                  "payment_status": state["payment_status"], "delivery_status": state["delivery_status"]})
            return
        if step in (3, 5, 6) and self._grant_expired(state):
            state.update(terminal=True, can_advance=False, payment_status="expired",
                         user_message="The 30-minute mission authority expired before purchase submission. No charge was made; the local budget reservation is released.")
            state["budget"] = {"reserved_cents": 0, "spent_cents": 0,
                               "available_cents": state["mission"]["budget_cents"]}
            self._event(state, step=step, stage="expired", title="The mission's authority has expired",
                        explanation="Belay checks expiry before signing, issuing a payment token and submitting checkout. An expired grant cannot begin this purchase. A purchase already submitted while valid would still need completion or reconciliation.",
                        actor="Authority service", sender="Belay", recipient="Belay authority", method="POST",
                        url="https://authority.belay.invalid/v1/actions/validate", status=403,
                        request={"operation_id": operation, "expires_at": state["grant"]["expires_at"]},
                        response={"allowed": False, "reason": "mission_expired", "purchase_submitted": False})
            return
        if step == 1:
            state["offer"] = {"total_cents": 28000, "currency": "USD", "seats": list(SEATS),
                              "seller": SELLER, "event": EVENT, "date": DATE, "venue": VENUE, "quantity": 2}
            state["user_message"] = "Found two adjacent seats for $280 total, including fees. I am checking the merchant's final checkout."
            self._event(state, step=1, stage="offers", title="The agent finds an eligible offer",
                        explanation="A scripted planner asks the fictional merchant for two adjacent seats. This is an offer, not a purchase.",
                        actor="Agent", sender="Belay agent", recipient="Merchant", method="GET",
                        url="https://merchant.belay.invalid/v1/offers",
                        request={"event": EVENT, "date": DATE, "quantity": 2}, response={"offer": state["offer"]})
        elif step == 2:
            if state["scenario"] == "price_change":
                state["offer"]["total_cents"] = 32000
            artifacts["checkout_id"] = "checkout_demo_" + operation
            state["user_message"] = f"The final checkout total is ${state['offer']['total_cents'] / 100:.2f}. I will check it against your mission before requesting payment credentials."
            self._event(state, step=2, stage="checkout", title="The merchant returns the final checkout",
                        explanation="The checkout pins exact seats and the inclusive final price. It does not charge the customer; Belay must validate this final offer.",
                        actor="Merchant", sender="Belay", recipient="Merchant", method="POST",
                        url="https://merchant.belay.invalid/v1/checkouts",
                        request={"operation_id": operation, "seat_ids": SEATS, "quantity": 2}, status=201,
                        response={"checkout_id": artifacts["checkout_id"], "total_cents": state["offer"]["total_cents"], "currency": "USD", "payment_required": True})
        elif step == 3:
            offer, grant = state["offer"], state["grant"]
            eligible = (grant["approved"] and offer["event"] == grant["event"]
                        and offer["date"] == grant["date"] and offer["venue"] == grant["venue"]
                        and offer["quantity"] == grant["quantity"]
                        and offer["seller"] == grant["seller"] and offer["currency"] == grant["currency"]
                        and offer["seats"] == SEATS and offer["total_cents"] <= grant["max_total_cents"])
            if not eligible:
                state.update(terminal=True, can_advance=False,
                             user_message="The final checkout exceeds or conflicts with the approved mission. No credential was issued and no purchase was submitted.")
                self._event(state, step=3, stage="blocked", title="The mission's limits stop the purchase",
                            explanation="Deterministic checks reject the final offer before reserving budget, signing or asking for a payment token. A model cannot expand the user's spending authority.",
                            actor="Authority service", sender="Belay agent", recipient="Belay authority", method="POST",
                            url="https://authority.belay.invalid/v1/actions/validate", status=403,
                            request={"total_cents": offer["total_cents"], "budget_cents": grant["max_total_cents"]},
                            response={"allowed": False, "payment_token_issued": False})
                return
            amount = offer["total_cents"]
            artifacts["intent"] = {"operation_id": operation, "checkout_id": artifacts["checkout_id"],
                                   "event": EVENT, "date": DATE, "venue": VENUE, "quantity": 2,
                                   "seller": SELLER, "seat_ids": list(SEATS), "amount_cents": amount, "currency": "USD"}
            artifacts["signature"] = "mocksig:delegated-action:" + operation
            artifacts["checkout_binding"] = "sha256:" + hashlib.sha256(encode(artifacts["intent"]).encode("utf-8")).hexdigest()
            artifacts["checkout_authorization"] = {
                "kind": "closed_checkout", "format": "illustrative_belay_demo_not_ap2",
                "checkout_binding": artifacts["checkout_binding"], "operation_id": operation,
                "checkout_id": artifacts["checkout_id"], "expires_at": grant["expires_at"],
                "signature": "mocksig:closed-checkout:" + operation,
            }
            state["budget"] = {"reserved_cents": amount, "spent_cents": 0,
                               "available_cents": state["mission"]["budget_cents"] - amount}
            state["user_message"] = "All mission rules matched. I reserved the total and saved this exact purchase before requesting a payment credential."
            self._event(state, step=3, stage="validated", title="Validate, reserve and save the exact intent",
                        explanation="Ordinary application code checks the mission and atomically reserves its budget with the saved intent. A protected key reference produces a mocksig marker; this demonstration performs no cryptography. Money has not moved.",
                        actor="Authority service", sender="Belay", recipient="Belay protected signer", method="POST",
                        url="https://authority.belay.invalid/v1/actions/sign",
                        request={"intent": artifacts["intent"], "key_reference": "demo_keyref_belay_agent"},
                        response={"allowed": True, "reserved_cents": amount, "signature": artifacts["signature"],
                                  "checkout_binding": artifacts["checkout_binding"], "demo_only": True})
        elif step == 4:
            artifacts["payment_mandate"] = {
                "format": "illustrative_belay_demo_not_ap2",
                "open_payment_authorization": {
                    "kind": "open_payment", "initial_grant": state["grant"],
                    "signature": state["grant"]["signature"],
                },
                "closed_payment_authorization": {
                    "kind": "closed_payment", "operation_id": operation,
                    "checkout_id": artifacts["checkout_id"], "checkout_binding": artifacts["checkout_binding"],
                    "seller": SELLER, "amount_cents": artifacts["intent"]["amount_cents"],
                    "currency": "USD", "expires_at": state["grant"]["expires_at"],
                    "signature": "mocksig:closed-payment:" + operation,
                },
            }
            state["user_message"] = "Requesting a restricted payment pass for this merchant and this exact checkout, under your original mission authority."
            self._event(state, step=4, stage="mandate", title="The approved intent becomes a payment request",
                        explanation="The illustrative open authorization carries the unchanged original mission approval. The closed payment and checkout authorizations bind to the same exact intent fingerprint. Signatures remain mocksig markers, not cryptography or AP2 messages, and no funds move.",
                        actor="Agent", sender="Belay", recipient="Credential provider", method="POST",
                        url="https://credentials.belay.invalid/v1/payment-mandates",
                        request=artifacts["payment_mandate"], response={"accepted": True, "funds_moved": False})
        elif step == 5:
            artifacts["payment_token"] = "demo_spt_" + operation
            state["payment_status"] = "credential_ready"
            state["user_message"] = "A restricted demo payment pass is ready for this exact purchase. No money has moved yet."
            self._event(state, step=5, stage="credential", title="A restricted demo payment token is issued",
                        explanation="This fictional token is scoped to the saved operation, seller and exact total. The card number and a user's private key never appear in the planner. Issuing the token does not move money.",
                        actor="Credential provider", sender="Credential provider", recipient="Belay", method="RESPONSE",
                        url="https://credentials.belay.invalid/v1/payment-tokens", status=201,
                        response={"token": artifacts["payment_token"], "seller": SELLER,
                                  "amount_cents": artifacts["intent"]["amount_cents"], "operation_id": operation,
                                  "demo_only": True, "funds_moved": False})
        elif step == 6:
            self._provider_submit(artifacts["intent"])
            state.update(payment_status="processing", order_status="pending", delivery_status="pending",
                         user_message="I submitted the approved checkout with its restricted payment pass and original operation ID. The merchant is processing it; tickets are not confirmed yet.")
            self._event(state, step=6, stage="submitted", title="The agent submits the checkout through an API",
                        explanation="The agent sends the saved checkout and token, using its original operation ID as the idempotency key. The local merchant now has a pending order; it has not captured payment.",
                        actor="Agent", sender="Belay", recipient="Merchant", method="POST",
                        url=f"https://merchant.belay.invalid/v1/checkouts/{artifacts['checkout_id']}/complete",
                        request={"headers": {"Authorization": "Bearer demo_merchant_access_NOT_REAL", "Idempotency-Key": operation},
                                 "body": {"operation_id": operation, "payment_token": artifacts["payment_token"],
                                          "intent": artifacts["intent"], "initial_grant": state["grant"],
                                          "closed_checkout_authorization": artifacts["checkout_authorization"]}},
                        response={"accepted": True, "order_status": "pending"}, status=202)
        elif step == 7:
            artifacts["payment_id"] = "pay_demo_" + operation
            state["user_message"] = "The merchant has asked its payment processor to charge this exact total. I am waiting for the bank's decision."
            self._event(state, step=7, stage="processing", title="The merchant asks its processor to take payment",
                        explanation="The merchant backend uses its own fictional processor API credential. The agent requested a purchase; the merchant and its processor execute the card-payment flow.",
                        actor="Merchant", sender="Merchant", recipient="Payment processor", method="POST",
                        url="https://processor.belay.invalid/v1/payments",
                        request={"headers": {"Authorization": "Bearer demo_processor_key_NOT_REAL", "Idempotency-Key": operation},
                                 "body": {"payment_token": artifacts["payment_token"], "amount_cents": artifacts["intent"]["amount_cents"], "currency": "USD"}},
                        response={"payment_id": artifacts["payment_id"], "status": "processing"}, status=202)
        elif step == 8:
            state["payment_status"] = "authorization_pending"
            state["user_message"] = "The payment request has reached the simulated issuing bank. Authorization is pending; no payment has been captured."
            self._provider_authorize(operation, "authorization_pending")
            self._event(state, step=8, stage="issuer_request", title="The payment network asks the issuing bank",
                        explanation="The processor routes an authorization request. This API-shaped trace simplifies real card-network messages; no live bank or network is contacted.",
                        actor="Payment processor", sender="Payment processor", recipient="Issuing bank", method="POST",
                        url="https://issuer.belay.invalid/v1/authorizations",
                        request={"payment_id": artifacts["payment_id"], "amount_cents": artifacts["intent"]["amount_cents"], "currency": "USD", "credential": "demo_network_reference"},
                        response={"status": "authorization_pending"}, status=202)
        elif step == 9:
            if state["scenario"] == "bank_verification":
                self._provider_authorize(operation, "requires_verification")
                state.update(needs_verification=True, can_advance=False, payment_status="requires_verification",
                             user_message="Your mission is approved, but the simulated bank requires verification. No payment has been captured.")
                stage, title, explanation, status = "bank_verification", "The bank requires an extra check", "The issuer pauses authorization for customer verification. This exception comes from the simulated bank; Belay cannot bypass it with the initial mission grant.", "requires_verification"
            elif state["scenario"] == "declined":
                self._provider_authorize(operation, "declined")
                state.update(terminal=True, can_advance=False, payment_status="declined", order_status="not_confirmed",
                             delivery_status="not_started", user_message="The bank declined authorization. No payment was captured and the reserved budget is available again.")
                state["budget"] = {"reserved_cents": 0, "spent_cents": 0, "available_cents": state["mission"]["budget_cents"]}
                stage, title, explanation, status = "declined", "The bank declines authorization", "A decline ends this attempt. There is no charge, no confirmed ticket order and no automatic retry with a different payment identity.", "declined"
            else:
                self._provider_authorize(operation, "authorized")
                state.update(payment_status="authorized", user_message="Payment is authorized. The merchant still needs to capture it and confirm the tickets.")
                stage, title, explanation, status = "authorized", "The bank authorizes the payment", "Authorization approves this payment request and may place a hold. Capture, merchant settlement and ticket delivery are different events; nothing is marked delivered yet.", "authorized"
            self._event(state, step=9, stage=stage, title=title, explanation=explanation,
                        actor="Issuing bank", sender="Issuing bank", recipient="Payment processor", method="RESPONSE",
                        url="https://issuer.belay.invalid/v1/authorizations",
                        response={"payment_id": artifacts["payment_id"], "status": status, "captured_cents": 0})
        elif step == 10:
            receipt = self._provider_capture(operation)
            if state["scenario"] == "lost_reply":
                state.update(payment_status="capture_unknown", order_status="unknown", delivery_status="unknown",
                             user_message="The checkout reply is missing. Belay has not confirmed the purchase; its budget remains reserved while it retrieves the original order.")
                self._event(state, step=10, stage="lost_reply", title="The provider commits, but Belay loses the reply",
                            explanation="The separate provider database has one captured payment and a fulfilled order. The app deliberately saves no receipt. This is a simulated timeout, not packet loss or SIGKILL; the original reservation remains until reconciliation.",
                            actor="Merchant", sender="Merchant", recipient="Belay", method="RESPONSE",
                            url=f"https://merchant.belay.invalid/v1/checkouts/{artifacts['checkout_id']}/complete", status="timeout",
                            response={"error": "simulated_reply_lost", "outcome_known_to_belay": False})
            else:
                if not self._record_receipt(state, receipt):
                    raise DemoError("The provider receipt did not match the saved intent", 409)
                state["user_message"] = "The processor captured the payment, and the merchant separately confirmed delivery of the two tickets."
                self._event(state, step=10, stage="receipts", title="Capture and merchant ticket confirmation arrive",
                            explanation="A capture receipt establishes payment; the merchant's separate order and ticket fields establish fulfillment. This local fixture completes both. Capture is not the merchant's later bank payout.",
                            actor="Merchant", sender="Merchant", recipient="Belay", method="RESPONSE",
                            url=f"https://merchant.belay.invalid/v1/orders/by-operation/{operation}",
                            response={"order_id": artifacts["order_id"], "payment_id": artifacts["payment_id"],
                                      "payment_status": "captured", "amount_cents": receipt["captured_cents"],
                                      "order_status": "confirmed", "delivery_status": "delivered", "tickets": state["tickets"]})
        elif step == 11:
            state.update(terminal=True, can_advance=False,
                         user_message="Your two adjacent tickets are confirmed. Belay completed the purchase under the initial mission authority.")
            self._event(state, step=11, stage="complete", title="Belay reports the verified result to you",
                        explanation="The notification uses recorded payment, order and delivery evidence. It does not ask the planner to guess whether an API timeout meant success.",
                        actor="Belay", sender="Belay", recipient="User", method="NOTIFY", url="local://mission-result",
                        response={"message": state["user_message"], "tickets": state["tickets"], "spent_cents": state["budget"]["spent_cents"]})
        else:
            raise DemoError("Unknown execution stage", 409)
