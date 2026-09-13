"""Durable local intent and an independent HTTP mock refund provider.

The provider's SQLite ledger is visible to the teaching UI's read-only grader.
Recovery only calls the provider's public lookup; opaque recovery cannot use
the grader. A negative lookup is authoritative in this synchronous mock only.
"""

import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCENARIOS = {"clean", "lost_ack", "before_send", "revoked", "opaque"}
MODES = {"belay", "naive", "idempotent"}
CRASH_EXIT = 86


class DemoError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@contextmanager
def connect(path):
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA synchronous=FULL")
    try:
        with db:
            yield db
    finally:
        db.close()


def event(db, case_id, kind, title, detail):
    db.execute("INSERT INTO events(case_id,kind,title,detail) VALUES(?,?,?,?)",
               (case_id, kind, title, detail))


class Provider:
    """Only this service mutates its external ledger."""

    def __init__(self, path):
        self.path = Path(path)
        self.token = secrets.token_urlsafe(32)
        with connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS refunds (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, reference TEXT NOT NULL,
                amount_cents INTEGER NOT NULL, created REAL NOT NULL)""")
            db.execute("CREATE TABLE IF NOT EXISTS capabilities (case_id TEXT PRIMARY KEY, opaque INTEGER NOT NULL)")
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def trusted(self):
                return (self.headers.get("X-Demo-Token") == provider.token
                        and self.headers.get("Origin") is None
                        and self.headers.get("Host") ==
                        "127.0.0.1:" + str(self.server.server_port))

            def do_GET(self):
                if not self.trusted():
                    return self.answer(403, {"error": "Internal mock-provider access only"})
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/refunds/lookup":
                    return self.answer(404, {"error": "Not found"})
                query = urllib.parse.parse_qs(parsed.query)
                if query.get("opaque") == ["1"]:
                    return self.answer(405, {"error": "This mock offers no lookup"})
                case_id = query.get("case_id", [""])[0]
                reference = query.get("reference", [""])[0]
                with connect(provider.path) as db:
                    capability = db.execute("SELECT opaque FROM capabilities WHERE case_id=?", (case_id,)).fetchone()
                    if capability and capability[0]:
                        return self.answer(405, {"error": "This mock offers no lookup"})
                    row = db.execute("SELECT id,amount_cents,reference FROM refunds "
                                     "WHERE case_id=? AND reference=?",
                                     (case_id, reference)).fetchone()
                self.answer(200, {"refund": dict(row) if row else None,
                                  "authoritative_for_synchronous_mock": True})

            def do_POST(self):
                if not self.trusted():
                    return self.answer(403, {"error": "Internal mock-provider access only"})
                if self.path != "/refunds":
                    return self.answer(404, {"error": "Not found"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        raise DemoError("Invalid request length")
                    body = json.loads(self.rfile.read(length))
                    case_id, reference = body["case_id"], body["reference"]
                    amount = body["amount_cents"]
                    if (not isinstance(case_id, str) or not isinstance(reference, str)
                            or type(amount) is not int or amount not in (3000, 5000)):
                        raise DemoError("Invalid synthetic refund")
                    if type(body.get("opaque")) is not bool:
                        raise DemoError("Invalid mock capability")
                    if not body["opaque"] and self.headers.get("Idempotency-Key") != reference:
                        raise DemoError("Idempotency key and reference must agree")
                    with connect(provider.path) as db:
                        db.execute("BEGIN IMMEDIATE")
                        db.execute("INSERT OR IGNORE INTO capabilities VALUES(?,?)", (case_id, int(body["opaque"])))
                        capability = db.execute("SELECT opaque FROM capabilities WHERE case_id=?", (case_id,)).fetchone()[0]
                        if bool(capability) != body["opaque"]:
                            raise DemoError("Mock provider capability cannot change for an existing case", 409)
                        prior = None
                        if not body.get("opaque"):
                            prior = db.execute("SELECT id,amount_cents,reference FROM refunds "
                                               "WHERE case_id=? AND reference=?",
                                               (case_id, reference)).fetchone()
                        if prior:
                            if prior["amount_cents"] != amount:
                                raise DemoError("Reference already belongs to another amount", 409)
                            refund = dict(prior)
                        else:
                            total = db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM refunds "
                                               "WHERE case_id=?", (case_id,)).fetchone()[0]
                            if total + amount > 10000:
                                raise DemoError("Synthetic $100 order cannot be over-refunded", 409)
                            refund = {"id": "rf_" + uuid.uuid4().hex[:16],
                                      "amount_cents": amount, "reference": reference}
                            db.execute("INSERT INTO refunds VALUES(?,?,?,?,?)",
                                       (refund["id"], case_id, reference, amount, time.time()))
                    # The transaction has committed before the HTTP receipt is written.
                    self.answer(200, {"refund": refund})
                except DemoError as exc:
                    self.answer(exc.status, {"error": str(exc)})
                except (ValueError, KeyError, TypeError):
                    self.answer(400, {"error": "Invalid JSON refund request"})
                except Exception:
                    self.answer(500, {"error": "Mock provider error"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def lookup(self, case_id, reference):
        query = urllib.parse.urlencode({"case_id": case_id, "reference": reference})
        req = urllib.request.Request(self.url + "/refunds/lookup?" + query,
                                     headers={"X-Demo-Token": self.token})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)["refund"]

    def grade(self, case_id):
        """Read-only presentation oracle. Never called by recovery decisions."""
        uri = self.path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT id,amount_cents,reference FROM refunds WHERE case_id=? ORDER BY created,id",
                (case_id,))]


class Engine:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "runtime.sqlite3"
        self.lock = threading.RLock()
        with connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,mode TEXT NOT NULL,scenario TEXT NOT NULL,
                status TEXT NOT NULL,anchor TEXT NOT NULL,amount_cents INTEGER,
                proposed_retry_cents INTEGER,authorized INTEGER NOT NULL,
                request_json TEXT,receipt_json TEXT,created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL,
                kind TEXT NOT NULL,title TEXT NOT NULL,detail TEXT NOT NULL)""")
        self.provider = Provider(self.data_dir / "provider.sqlite3")

    def close(self):
        self.provider.close()

    def _row(self, case_id):
        with connect(self.path) as db:
            row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise DemoError("Case not found", 404)
        return dict(row)

    def _request(self, row, amount, reference):
        return {"method": "POST", "url": self.provider.url + "/refunds",
                "headers": ({"Content-Type": "application/json"} if row["scenario"] == "opaque"
                            else {"Content-Type": "application/json", "Idempotency-Key": reference}),
                "body": {"case_id": row["id"], "order_id": "demo_order_" + row["id"],
                         "amount_cents": amount, "reference": reference,
                         "opaque": row["scenario"] == "opaque"}}

    def create(self, scenario, mode):
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            raise DemoError("Unknown scenario")
        if not isinstance(mode, str) or mode not in MODES:
            raise DemoError("Unknown mode")
        with self.lock:
            case_id = uuid.uuid4().hex
            anchor = "refund_" + uuid.uuid4().hex
            # Anchor is committed before the scripted decision is evaluated.
            with connect(self.path) as db:
                db.execute("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (case_id, mode, scenario, "pending", anchor, None, None,
                            1, None, None, time.time()))
                event(db, case_id, "anchor", "Effect identity saved",
                      "Opaque refund identity committed before the scripted decision." if mode == "belay"
                      else ("The existing-provider baseline persists a stable key and the original intent."
                            if mode == "idempotent" else
                            "Initial attempt identity; this baseline will replace it on retry."))
            amount = 5000  # Deliberately scripted, not a real model invocation.
            row = self._row(case_id)
            request = self._request(row, amount, anchor)
            with connect(self.path) as db:
                db.execute("UPDATE cases SET amount_cents=?,request_json=? WHERE id=?",
                           (amount, json.dumps(request), case_id))
                event(db, case_id, "intent", "Refund intent saved: $50",
                      "A $100 order has an authorized $50 refund. All funds and decisions are synthetic.")
            crash = "none" if scenario == "clean" else (
                "before_send" if scenario in ("before_send", "revoked") else "after_commit")
            self._run_worker(case_id, request, crash)
            if scenario == "revoked":
                with connect(self.path) as db:
                    db.execute("UPDATE cases SET authorized=0 WHERE id=?", (case_id,))
                    event(db, case_id, "permission", "Permission revoked during downtime",
                          "Recovery must read the current permission before creating any new refund.")
            return self.get(case_id)

    def _run_worker(self, case_id, request, crash):
        payload = {"db": str(self.path), "case_id": case_id, "request": request,
                   "token": self.provider.token, "crash": crash}
        with connect(self.path) as db:
            event(db, case_id, "dispatch", "Worker started",
                  "A separate OS process will call the HTTP mock provider." if crash != "before_send"
                  else "The worker will exit abruptly before sending the HTTP request.")
        result = subprocess.run([sys.executable, "-m", "prototype.engine", "--worker"],
                                input=json.dumps(payload), text=True, capture_output=True,
                                cwd=str(Path(__file__).resolve().parents[1]), timeout=15)
        with connect(self.path) as db:
            if result.returncode == CRASH_EXIT:
                event(db, case_id, "crash", "Worker died; local receipt missing",
                      "The worker received the HTTP receipt, then os._exit(86) ran before it could save that receipt locally."
                      if crash == "after_commit" else
                      "os._exit(86) ran before the request was sent. The runtime only has durable intent.")
            elif result.returncode != 0:
                # A transport failure is ambiguous; never call the effect failed.
                event(db, case_id, "error", "Worker outcome is unknown",
                      "The worker returned an error. Provider reconciliation is required before another attempt.")

    def recover(self, case_id):
        with self.lock:
            row = self._row(case_id)
            if row["status"] in ("completed", "blocked", "permission_denied"):
                return self.get(case_id)
            if row["amount_cents"] is None:
                # No durable intent means no submission could have occurred.
                with connect(self.path) as db:
                    db.execute("UPDATE cases SET amount_cents=5000 WHERE id=?", (case_id,))
                    event(db, case_id, "intent", "Unstarted decision resumed",
                          "No durable intent existed; no external request could have been made.")
                row = self._row(case_id)
            if row["mode"] == "belay":
                if row["scenario"] == "opaque":
                    with connect(self.path) as db:
                        db.execute("UPDATE cases SET status='blocked' WHERE id=?", (case_id,))
                        event(db, case_id, "blocked", "Stopped: provider cannot resolve this anchor",
                              "No lookup and no idempotency support. Retrying could duplicate the refund; status remains unknown.")
                    return self.get(case_id)
                with connect(self.path) as db:
                    event(db, case_id, "lookup", "Ask provider about the original anchor",
                          "A read-only lookup creates no new refund and does not require refund permission.")
                try:
                    receipt = self.provider.lookup(case_id, row["anchor"])
                except (OSError, ValueError, urllib.error.URLError):
                    with connect(self.path) as db:
                        event(db, case_id, "error", "Lookup unavailable; no retry sent",
                              "Recovery remains pending until trustworthy evidence is available.")
                    return self.get(case_id)
                if receipt:
                    if (receipt.get("reference") != row["anchor"]
                            or receipt.get("amount_cents") != row["amount_cents"]):
                        with connect(self.path) as db:
                            db.execute("UPDATE cases SET status='blocked' WHERE id=?", (case_id,))
                            event(db, case_id, "blocked", "Provider evidence does not match intent",
                                  "The anchored amount and returned receipt disagree; no new refund issued.")
                    else:
                        with connect(self.path) as db:
                            db.execute("UPDATE cases SET status='completed',receipt_json=? WHERE id=?",
                                       (json.dumps(receipt), case_id))
                            event(db, case_id, "recovered", "Original $50 receipt recovered",
                                  "The original refund already committed. Recorded its receipt without issuing another refund.")
                    return self.get(case_id)
                with connect(self.path) as db:
                    event(db, case_id, "not_found", "Synchronous mock confirms no refund exists",
                          "This mock completes submissions before recovery. A production not-found response alone may not prove that.")
                amount, reference = row["amount_cents"], row["anchor"]
            elif row["mode"] == "idempotent":
                if row["scenario"] == "opaque":
                    with connect(self.path) as db:
                        db.execute("UPDATE cases SET status='blocked' WHERE id=?", (case_id,))
                        event(db, case_id, "blocked", "Stopped: provider offers no idempotency",
                              "A stable key only prevents duplicates when the provider honors it. No retry is sent.")
                    return self.get(case_id)
                amount, reference = row["amount_cents"], row["anchor"]
                with connect(self.path) as db:
                    event(db, case_id, "idempotency", "Retry the same $50 with the same key",
                          "Existing provider idempotency can return the original receipt. No lookup or new decision is needed.")
            else:
                amount, reference = 3000, "retry_" + uuid.uuid4().hex
                with connect(self.path) as db:
                    db.execute("UPDATE cases SET proposed_retry_cents=? WHERE id=?", (amount, case_id))
                    event(db, case_id, "divergence", "Scripted retry chooses $30 and a new key",
                          "This intentionally naive baseline reruns its decision without reconciling the earlier $50 attempt. No LLM is called.")
            # Fresh permission is checked here and again inside the worker before HTTP.
            row = self._row(case_id)
            if not row["authorized"]:
                with connect(self.path) as db:
                    db.execute("UPDATE cases SET status='permission_denied' WHERE id=?", (case_id,))
                    event(db, case_id, "permission", "New refund refused: permission revoked",
                          "An earlier permission is not replayed. No HTTP refund request is sent.")
                return self.get(case_id)
            request = self._request(row, amount, reference)
            with connect(self.path) as db:
                db.execute("UPDATE cases SET request_json=? WHERE id=?", (json.dumps(request), case_id))
            self._run_worker(case_id, request, "none")
            return self.get(case_id)

    def get(self, case_id):
        with self.lock:
            row = self._row(case_id)
            with connect(self.path) as db:
                events = [dict(item) for item in db.execute(
                    "SELECT kind,title,detail FROM events WHERE case_id=? ORDER BY seq", (case_id,))]
            refunds = self.provider.grade(case_id)
            total = sum(refund["amount_cents"] for refund in refunds)
            status = row["status"]
            if status == "blocked":
                outcome = {"title": "Stopped with an unknown outcome", "detail":
                           "Recovery cannot determine whether the refund committed. The teaching ledger is visible below, but is unavailable to recovery."}
            elif status == "permission_denied":
                outcome = {"title": "No new refund: permission was revoked", "detail":
                           "Recovery checked live permission before creating another external effect."}
            elif status == "completed" and row["mode"] == "naive" and total > 5000:
                outcome = {"title": "Two refunds: $80 instead of the intended $50", "detail":
                           "The new $30 attempt used a different key. The provider correctly treated it as another refund on the $100 order."}
            elif status == "completed" and total < row["amount_cents"]:
                outcome = {"title": "Refund differs from original intent", "detail":
                           f"The provider paid ${total / 100:.2f}; "
                           f"${(row['amount_cents'] - total) / 100:.2f} less than the saved intent. "
                           "A successful API receipt does not mean the original decision was fulfilled."}
            elif status == "completed":
                outcome = {"title": "Refund receipt recorded", "detail":
                           "The runtime has a receipt. Compare the independent provider ledger with the original $50 intent."}
            else:
                outcome = {"title": "Recovery needed: no local receipt", "detail":
                           "The worker stopped. The runtime must establish what happened before it creates another refund."}
            return {"id": case_id, "mode": row["mode"], "scenario": row["scenario"],
                    "status": status, "anchor": row["anchor"], "amount_cents": row["amount_cents"],
                    "order_amount_cents": 10000, "proposed_retry_cents": row["proposed_retry_cents"],
                    "authorized": bool(row["authorized"]), "total_refunded_cents": total,
                    "refunds": refunds, "events": events, "request": json.loads(row["request_json"] or "null"),
                    "outcome": outcome, "provider_evidence_label": "Independent teaching ledger; not a recovery oracle"}

    def list_cases(self):
        with self.lock:
            with connect(self.path) as db:
                ids = [row[0] for row in db.execute("SELECT id FROM cases ORDER BY created DESC")]
            return [self.get(case_id) for case_id in ids]


def worker(payload):
    path, case_id = payload["db"], payload["case_id"]
    if payload["crash"] == "before_send":
        os._exit(CRASH_EXIT)
    with connect(path) as db:
        authorized = db.execute("SELECT authorized FROM cases WHERE id=?", (case_id,)).fetchone()
        if not authorized or not authorized[0]:
            db.execute("UPDATE cases SET status='permission_denied' WHERE id=?", (case_id,))
            event(db, case_id, "permission", "Worker refused revoked permission", "No HTTP request was sent.")
            return
    request = payload["request"]
    headers = dict(request["headers"])
    headers["X-Demo-Token"] = payload["token"]
    req = urllib.request.Request(request["url"], data=json.dumps(request["body"]).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as response:
        receipt = json.load(response)["refund"]
    if payload["crash"] == "after_commit":
        os._exit(CRASH_EXIT)  # No exception/finally cleanup; receipt never enters runtime DB.
    with connect(path) as db:
        db.execute("UPDATE cases SET status='completed',receipt_json=? WHERE id=?",
                   (json.dumps(receipt), case_id))
        event(db, case_id, "receipt", "Provider receipt saved",
              f"Recorded a ${receipt['amount_cents'] / 100:.2f} synthetic refund "
              f"under reference {receipt['reference']}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if not args.worker:
        parser.error("Use python -m prototype.server to run the teaching app")
    worker(json.load(sys.stdin))
