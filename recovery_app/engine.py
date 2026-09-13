"""Persistent recovery incidents; the model proposes and never executes.

Local simulations use the same journal, evidence and application checks as the
research experiments. Arc evidence is read from a fixed testnet adapter; only
the user's browser wallet can send a transaction. One process owns a data
directory, and mutations are serialized within that process.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from belay.authz import PermissionStore
from belay.journal import Journal
from second.adjudicate import adjudicate, escalated_slots
from second.agent import DebugAgent
from second.apply import CLOSED_FROM_EVIDENCE, COMPLETED, REFUSED, apply_dossier
from second.dossier import Dossier, Proposal, ProposalKind, Verdict
from second.evidence import EvidenceStore
from services.ledger import Ledger

SCENARIOS = [
    {"id": "lost_ack", "title": "Did the refund happen?",
     "description": "A $50 refund lost its acknowledgment. Inspect the processor's record before acting."},
    {"id": "never_sent", "title": "Finish an interrupted refund",
     "description": "The request stopped before reaching the processor. Establish absence before completing it."},
    {"id": "stale_report", "title": "The report is too old",
     "description": "A silent report predates the request. Ask for an updated statement."},
    {"id": "conflicting_sources", "title": "Two sources disagree",
     "description": "One report claims nothing happened; another contains the refund. Surface the conflict."},
    {"id": "revoked", "title": "Permission changed",
     "description": "Investigate a missing refund, then see the current permission block a new payment."},
    {"id": "no_evidence", "title": "Know when to stop",
     "description": "There is no reliable outcome record. Identify the evidence needed to decide."},
]
SCOPE = "payments:refund"


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _fingerprint(directory):
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class _Recorder:
    def __init__(self, delegate):
        self.delegate = delegate
        self.observations = []
        self.claim = None

    def propose_pointers(self, view):
        return self.delegate.propose_pointers(view)

    def conclude(self, view, observations):
        self.observations = [item.as_dict() for item in observations]
        claim = self.delegate.conclude(view, observations)
        self.claim = claim.as_dict()
        return claim


class Engine:
    def __init__(self, data_dir=".belay-recovery", *, arc_provider=None, agent_factories=None):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._mutex = threading.RLock()
        self._lease = (self.data_dir / ".owner.lock").open("a+b")
        try:
            if os.fstat(self._lease.fileno()).st_size == 0:
                self._lease.write(b"0")
                self._lease.flush()
            self._lease.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lease.close()
            raise AppError("This recovery data directory is already open in another process", 409) from exc
        self._arc = arc_provider
        self._factories = agent_factories or {}
        self._closed = False

    def close(self):
        # Do not release ownership while a request is still using its state.
        with self._mutex:
            if not self._closed:
                self._closed = True
                self._lease.close()

    def _ensure_open(self):
        if self._closed:
            raise AppError("This Recovery Desk has been closed", 503)

    def config(self):
        self._ensure_open()
        from recovery_app.arc import network_config
        available = True
        try:
            self._agent("openai")
        except (ValueError, AppError):
            available = False
        return {
            "mode": "live", "product": "Belay Recovery Desk",
            "agents": [
                {"id": "heuristic", "label": "Deterministic baseline", "available": True},
                {"id": "openai", "label": "OpenAI evidence assistant", "available": available},
            ],
            "scenarios": SCENARIOS,
            "wallet": {**network_config(), "enabled": True},
            "disclosure": "Local simulations or user-signed Arc Testnet transactions; no real money. Models only propose evidence interpretations.",
        }

    def _agent(self, name):
        if name in self._factories:
            return self._factories[name]()
        if name == "heuristic":
            return DebugAgent(hallucination_p=0, overconfidence_p=0, laziness_p=0, seed=0)
        if name == "openai":
            from second.live_agent import OpenAIRecoveryAgent
            return OpenAIRecoveryAgent.from_env()
        raise AppError("Choose an available recovery assistant")

    def _directory(self, incident_id):
        if not isinstance(incident_id, str) or not re.fullmatch(r"[a-f0-9]{32}", incident_id):
            raise AppError("Incident not found", 404)
        directory = self.data_dir / incident_id
        if directory.is_symlink() or not (directory / "incident.json").is_file():
            raise AppError("Incident not found", 404)
        return directory

    def _load(self, incident_id):
        self._ensure_open()
        directory = self._directory(incident_id)
        incident = json.loads((directory / "incident.json").read_text(encoding="utf-8"))
        if incident["provider"] == "arc":
            records = self._journal(incident).read()
            dispatched = any(row.get("kind") == "wallet_dispatch" for row in records)
            incident["wallet"]["dispatched"] = dispatched
            hashes = {row["transaction_hash"] for row in records if row.get("kind") == "wallet_transaction"}
            if len(hashes) > 1:
                raise AppError("Conflicting transaction identities in the durable journal", 409)
            incident["wallet"]["transaction_hash"] = next(iter(hashes), None)
            if dispatched and not any(row.get("kind") == "escalated" for row in records):
                self._halt(incident, "recovered wallet dispatch without an acknowledged outcome")
            if dispatched and incident["status"] == "prepared":
                incident["status"] = "unresolved"
        else:
            records = self._journal(incident).read()
            if (any(row.get("kind") == "application_dispatch" for row in records)
                    and not any(row.get("kind") == "escalated" for row in records)):
                self._halt(incident, "recovered local provider attempt without an acknowledged outcome")
        return incident

    def _save(self, incident):
        _write(self.data_dir / incident["id"] / "incident.json", incident)

    def _journal(self, incident):
        return Journal(str(self.data_dir / incident["id"] / "journal.jsonl"), incident["id"])

    def _perms(self, incident):
        return PermissionStore(str(self.data_dir / incident["id"] / "perms.json"))

    def _event(self, incident, kind, title, detail=""):
        incident["timeline"].append({"kind": kind, "title": title, "detail": detail, "ts": time.time()})

    def _new(self, *, title, scenario, provider, amount_cents, wallet=None):
        self._ensure_open()
        incident_id = uuid.uuid4().hex
        directory = self.data_dir / incident_id
        directory.mkdir()
        (directory / "evidence").mkdir()
        incident = {
            "id": incident_id, "title": title, "scenario": scenario, "provider": provider,
            "status": "unresolved", "created_at": time.time(), "timeline": [],
            "intent": {"order_id": "order-" + incident_id, "amount_cents": amount_cents,
                       "scope": SCOPE, "anchor": uuid.uuid4().hex, "asset": "test USDC" if wallet else "demo USD"},
            "proposal": None, "outcome": None, "wallet": wallet,
        }
        journal = self._journal(incident)
        intent = incident["intent"]
        journal.append("anchor", slot="refund", anchor=intent["anchor"])
        journal.append("intent", slot="refund", anchor=intent["anchor"],
                       amount=amount_cents, scope=SCOPE, order_id=intent["order_id"])
        self._perms(incident).grant_all([SCOPE])
        self._event(incident, "intent", "Original request preserved", "The amount and identity come from this request, not from the assistant.")
        return incident

    def _halt(self, incident, reason):
        self._journal(incident).append("escalated", slot="refund", anchor=incident["intent"]["anchor"], reason=reason)

    def _simulation_records(self, incident):
        ledger = Ledger(str(self.data_dir / incident["id"] / "ledger.db"))
        try:
            return [{"kind": "refund", "order_id": row["order_id"], "amount_cents": row["amount_cents"],
                     "external_id": row["id"], "ts": row["ts"]} for row in ledger.for_order(incident["intent"]["order_id"])]
        finally:
            ledger.close()

    def _simulation_commit(self, incident, amount):
        ledger = Ledger(str(self.data_dir / incident["id"] / "ledger.db"))
        try:
            external_id = ledger.commit_effect("payments", "refund", incident["intent"]["order_id"], amount)
            return SimpleNamespace(external_id=external_id, amount_cents=amount)
        finally:
            ledger.close()

    def _source(self, incident, name, records, coverage):
        _write(self.data_dir / incident["id"] / "evidence" / (name + ".json"),
               {"records": records, "coverage": coverage})

    def create(self, scenario):
        with self._mutex:
            selected = next((item for item in SCENARIOS if item["id"] == scenario), None)
            if selected is None:
                raise AppError("Unknown demo scenario")
            incident = self._new(title=selected["title"], scenario=scenario, provider="simulation", amount_cents=5000)
            # The incident must remain discoverable even if the provider commits
            # and the process stops before evidence/display state is written.
            self._save(incident)
            self._journal(incident).append("application_dispatch", slot="refund", anchor=incident["intent"]["anchor"])
            # Real SQLite writes; interruption is controlled, not an OS-kill claim.
            if scenario in {"lost_ack", "stale_report", "conflicting_sources", "no_evidence"}:
                self._simulation_commit(incident, 5000)
            self._halt(incident, "controlled acknowledgment loss in local payment simulator")
            records = self._simulation_records(incident)
            coverage = {"kind": "complete_until", "cutoff_ts": time.time()}
            if scenario == "stale_report":
                self._source(incident, "settlement_report", [], {"kind": "complete_until", "cutoff_ts": incident["created_at"] - 60})
            elif scenario == "conflicting_sources":
                self._source(incident, "settlement_report", [], coverage)
                self._source(incident, "processor_receipt", records, {"kind": "lossy", "drop_rate": 0.1})
            elif scenario != "no_evidence":
                self._source(incident, "settlement_report", records, coverage)
            if scenario == "revoked":
                self._perms(incident).revoke(SCOPE)
            self._event(incident, "interrupted", "Acknowledgment unavailable", "Controlled local simulation. Investigate before issuing another refund.")
            self._save(incident)
            return self.get(incident["id"])

    def _present(self, incident):
        result = json.loads(json.dumps(incident))
        records = self._journal(incident).read()
        result["revision"] = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
        result["permission"] = {"active": self._perms(incident).held(SCOPE)}
        closed = next((row for row in reversed(records) if row.get("kind") == "adjudicated"), None)
        if closed:
            result["status"] = "resolved"
            if not result.get("outcome"):
                result["outcome"] = {"action": "closed_from_journal", "note": "A durable resolution was recovered after restart.", "record": closed}
        proposal = result.get("proposal")
        if proposal:
            proposal.pop("dossier", None)
            proposal["can_apply"] = (result["status"] != "resolved" and proposal["verdict"] != "abstain")
            if proposal["verdict"] == "absent" and not result["permission"]["active"]:
                proposal["can_apply"] = False
        result["next_steps"] = self._next_steps(result)
        return result

    def get(self, incident_id):
        with self._mutex:
            return self._present(self._load(incident_id))

    def list_incidents(self):
        with self._mutex:
            self._ensure_open()
            entries = []
            for path in self.data_dir.glob("*/incident.json"):
                if re.fullmatch(r"[a-f0-9]{32}", path.parent.name) and not path.parent.is_symlink():
                    entries.append(self.get(path.parent.name))
            return sorted(entries, key=lambda entry: entry["created_at"], reverse=True)

    def _next_steps(self, incident):
        if incident["status"] == "resolved":
            return [{"title": "Resolution recorded", "detail": "Download the evidence receipt for this incident.", "action": None}]
        if incident["provider"] == "arc":
            if not incident["wallet"].get("transaction_hash"):
                return [{"title": "Find the transaction hash", "detail": "Check MetaMask Activity and attach the hash. Do not send again while the outcome is unknown.", "action": None}]
            return [{"title": "Check the finalized transaction", "detail": "Read the original transaction and finalized receipt from Arc; a missing receipt is not absence.", "action": "probe"}]
        proposal = incident.get("proposal") or {}
        notes = " ".join(proposal.get("validator_notes", [])).lower()
        if "conflict" in notes or incident["scenario"] == "conflicting_sources" and not proposal:
            return [{"title": "Reconcile the conflicting reports", "detail": "Refresh both demo sources from the local processor and investigate the new snapshots.", "action": "probe"}]
        if not incident["permission"]["active"]:
            return [{"title": "No new refund is authorized", "detail": "You can inspect an existing payment, but completion requires a separately authorized request.", "action": None}]
        return [{"title": "Request an up-to-date processor statement", "detail": "Refresh the local provider evidence, including coverage through the attempted action.", "action": "probe"}]

    def investigate(self, incident_id, agent_name):
        with self._mutex:
            incident = self._load(incident_id)
            if self.get(incident_id)["status"] == "resolved":
                raise AppError("This incident already has a durable resolution", 409)
            if incident["provider"] == "arc":
                self._refresh_arc(incident)
            slots = escalated_slots(str(self.data_dir / incident_id), incident["intent"]["order_id"])
            if len(slots) != 1:
                raise AppError("A dispatched, unresolved incident is required", 409)
            try:
                delegate = self._agent(agent_name)
            except ValueError as exc:
                raise AppError("The model is not configured. Set OPENAI_API_KEY and OPENAI_MODEL on the local server.", 503) from exc
            recorder = _Recorder(delegate)
            started = time.perf_counter()
            evidence = self.data_dir / incident_id / "evidence"
            dossier = adjudicate(slots[0], EvidenceStore(str(evidence)), recorder)
            if incident["provider"] == "arc" and dossier.verdict is Verdict.ABSENT:
                dossier = Dossier.abstain(slots[0].anchor, slots[0].slot, "Arc recovery never authorizes another transfer from a missing receipt.")
            metrics = delegate.metrics() if callable(getattr(delegate, "metrics", None)) else {
                "provider": "heuristic", "transport": "local", "requests": 0, "estimated_cost_usd": 0,
            }
            incident["proposal"] = {
                "id": uuid.uuid4().hex, "verdict": dossier.verdict.value,
                "reasoning": dossier.reasoning, "validator_notes": dossier.validator_notes,
                "citations": dossier.citations, "observations": recorder.observations,
                "claim": recorder.claim, "agent": agent_name, "metrics": metrics,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "dossier": dossier.as_dict(), "evidence_revision": _fingerprint(evidence),
                "can_apply": dossier.resolved,
            }
            incident["status"] = "needs_evidence" if dossier.verdict is Verdict.ABSTAIN else "ready"
            self._event(incident, "investigated", "Evidence checked", "; ".join(dossier.validator_notes))
            self._save(incident)
            return self.get(incident_id)

    def resolve(self, incident_id, proposal_id):
        with self._mutex:
            incident = self._load(incident_id)
            proposal = incident.get("proposal")
            if self.get(incident_id)["status"] == "resolved":
                raise AppError("This incident is already resolved; no action was repeated", 409)
            if not proposal or proposal_id != proposal["id"]:
                raise AppError("Investigate the incident and use its current proposal", 409)
            if proposal["evidence_revision"] != _fingerprint(self.data_dir / incident_id / "evidence"):
                raise AppError("Evidence changed; investigate again before resolving", 409)
            raw = proposal["dossier"]
            shape = raw["proposal"]
            dossier = Dossier(**{**raw, "verdict": Verdict(raw["verdict"]),
                                 "proposal": Proposal(ProposalKind(shape["kind"]), shape["scope"], shape["amount_cents"])})
            if dossier.verdict is Verdict.ABSTAIN:
                raise AppError("Evidence does not support a resolution", 409)
            if incident["provider"] == "arc" and dossier.verdict is not Verdict.COMMITTED:
                raise AppError("Only an existing finalized Arc transfer can be recorded; Belay cannot issue one", 409)
            applied = apply_dossier(dossier, journal=self._journal(incident), perms=self._perms(incident),
                                    issue_effect=lambda amount: self._simulation_commit(incident, amount),
                                    operator="local-recovery-operator")
            incident["outcome"] = {"action": applied.action, "note": applied.note,
                                   "external_id": applied.external_id,
                                   "transaction_hash": (incident.get("wallet") or {}).get("transaction_hash")}
            incident["status"] = "resolved" if applied.action in {CLOSED_FROM_EVIDENCE, COMPLETED} else "refused" if applied.action == REFUSED else "unresolved"
            self._event(incident, "resolved", "Resolution recorded" if incident["status"] == "resolved" else "Action withheld", applied.note)
            self._save(incident)
            return self.get(incident_id)

    def probe(self, incident_id):
        with self._mutex:
            incident = self._load(incident_id)
            if self.get(incident_id)["status"] == "resolved":
                raise AppError("This incident is already resolved", 409)
            if incident["provider"] == "arc":
                self._refresh_arc(incident)
            else:
                records = self._simulation_records(incident)
                coverage = {"kind": "complete_until", "cutoff_ts": time.time()}
                self._source(incident, "settlement_report", records, coverage)
                if incident["scenario"] == "conflicting_sources":
                    self._source(incident, "processor_receipt", records, {"kind": "lossy", "drop_rate": 0.1})
            incident["proposal"] = None
            incident["status"] = "unresolved"
            self._event(incident, "probe", "Provider evidence refreshed", "Read-only lookup. No payment was issued; investigate the new snapshot.")
            self._save(incident)
            return self.get(incident_id)

    def revoke(self, incident_id):
        with self._mutex:
            incident = self._load(incident_id)
            self._perms(incident).revoke(SCOPE)
            self._event(incident, "permission", "Permission revoked", "Belay will not start a new wallet request. This cannot cancel an already-open MetaMask prompt or undo a signed transfer; reject any pending prompt in MetaMask.")
            self._save(incident)
            return self.get(incident_id)

    def receipt(self, incident_id):
        with self._mutex:
            incident = self.get(incident_id)
            return {"schema_version": 1, "incident": incident, "journal": self._journal(incident).read(),
                    "scope": "Local audit record, not a cryptographic attestation of external truth.",
                    "execution": "Arc Testnet RPC evidence" if incident["provider"] == "arc" else "Local simulated payment provider"}

    def _arc_provider(self):
        if self._arc is None:
            from recovery_app.arc import ArcEvidenceProvider
            self._arc = ArcEvidenceProvider()
        return self._arc

    def prepare_wallet(self, sender, recipient, amount_units):
        from recovery_app.arc import CHAIN_ID, TOKEN_ADDRESS, prepare_transaction
        with self._mutex:
            self._ensure_open()
            if not all(isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value) for value in (sender, recipient)):
                raise AppError("Use valid public wallet addresses")
            if int(sender, 16) == 0 or int(recipient, 16) == 0 or sender.lower() == recipient.lower():
                raise AppError("Use distinct nonzero sender and recipient wallets")
            if type(amount_units) is not int or not 10_000 <= amount_units <= 1_000_000 or amount_units % 10_000:
                raise AppError("Use 0.01 to 1.00 test USDC in 0.01 increments")
            for other in self.list_incidents():
                wallet = other.get("wallet") or {}
                if (other["status"] != "resolved" and wallet.get("sender") == sender.lower()
                        and wallet.get("recipient") == recipient.lower() and wallet.get("amount_units") == amount_units):
                    raise AppError("An identical test transfer is still unresolved. Open that incident and attach its original transaction hash instead of sending again.", 409)
            try:
                head = self._arc_provider().head()
            except (ValueError, RuntimeError, OSError) as exc:
                raise AppError("Arc Testnet could not be verified. No wallet transfer was requested.", 503) from exc
            wallet = {"sender": sender.lower(), "recipient": recipient.lower(), "amount_units": amount_units,
                      "chain_id": CHAIN_ID, "token": TOKEN_ADDRESS, "min_block_number": head["block_number"],
                      "transaction_hash": None, "dispatched": False}
            incident = self._new(title="Recover a test USDC transfer", scenario="arc_transfer", provider="arc",
                                 amount_cents=amount_units // 10_000, wallet=wallet)
            incident["status"] = "prepared"
            self._save(incident)
            result = self.get(incident["id"])
            result["transaction"] = prepare_transaction(sender, recipient, amount_units)
            return result

    def dispatch_wallet(self, incident_id):
        with self._mutex:
            incident = self._load(incident_id)
            if incident["provider"] != "arc" or incident["wallet"]["dispatched"]:
                raise AppError("A wallet request was already started. Inspect it or attach its hash; do not send again.", 409)
            if not self._perms(incident).held(SCOPE):
                raise AppError("Permission was revoked before the wallet request", 403)
            # The durable marker is authoritative even if saving incident.json fails.
            journal = self._journal(incident)
            if any(row.get("kind") == "wallet_dispatch" for row in journal.read()):
                raise AppError("A wallet request may already exist; recover its transaction hash", 409)
            journal.append("wallet_dispatch", slot="refund", anchor=incident["intent"]["anchor"])
            self._halt(incident, "wallet request started; receipt intentionally not acknowledged locally")
            incident["wallet"]["dispatched"] = True
            incident["status"] = "unresolved"
            self._event(incident, "dispatch", "Wallet request started", "A signed transaction may exist. A missing hash cannot authorize another send.")
            self._save(incident)
            return self.get(incident_id)

    def attach_transaction(self, incident_id, transaction_hash):
        with self._mutex:
            if not isinstance(transaction_hash, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", transaction_hash):
                raise AppError("A transaction hash must be 0x followed by 64 hexadecimal characters")
            transaction_hash = transaction_hash.lower()
            incident = self._load(incident_id)
            dispatched = any(row.get("kind") == "wallet_dispatch" for row in self._journal(incident).read())
            if incident["provider"] != "arc" or not dispatched:
                raise AppError("No wallet request was started for this incident", 409)
            if incident["wallet"].get("transaction_hash") not in (None, transaction_hash):
                raise AppError("This incident already tracks a different transaction", 409)
            for other in self.list_incidents():
                if other["id"] != incident_id and (other.get("wallet") or {}).get("transaction_hash") == transaction_hash:
                    raise AppError("That transaction is already assigned to another incident", 409)
            self._journal(incident).append("wallet_transaction", transaction_hash=transaction_hash,
                                           slot="refund", anchor=incident["intent"]["anchor"])
            incident["wallet"]["transaction_hash"] = transaction_hash
            incident["wallet"]["dispatched"] = True
            incident["proposal"] = None
            incident["status"] = "unresolved"
            self._event(incident, "transaction", "Transaction hash saved", "The receipt is intentionally unacknowledged. Investigate its finalized on-chain outcome.")
            self._save(incident)
            return self.get(incident_id)

    def _refresh_arc(self, incident):
        result = self._arc_provider().read(incident["wallet"])
        incident["provider_evidence"] = result
        records = []
        if result["status"] == "committed":
            for record in result["records"]:
                records.append({**record, "kind": "refund", "order_id": incident["intent"]["order_id"],
                                "amount_cents": incident["intent"]["amount_cents"], "external_id": None,
                                "chain_id": incident["wallet"]["chain_id"],
                                "ts": time.time()})
        # A finalized matching receipt can show commitment. Silence never proves absence.
        self._source(incident, "arc_finalized_receipt", records, {"kind": "lossy", "drop_rate": 1})
