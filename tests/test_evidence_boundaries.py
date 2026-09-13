"""Offline regressions for model-selected evidence and refund identity.

Every model response is injected locally. Files and payment records are
synthetic temporary fixtures; these tests never use credentials or a network.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from belay.authz import PermissionStore  # noqa: E402
from belay.journal import Journal  # noqa: E402
from second.adjudicate import adjudicate, escalated_slots, validate  # noqa: E402
from second.apply import COMPLETED, INCONSISTENT, NONE, apply_dossier  # noqa: E402
from second.dossier import Claim, Verdict  # noqa: E402
from second.evidence import EvidenceStore, Observation, Pointer  # noqa: E402
from second.live_agent import OpenAIRecoveryAgent, RecoveryModelError  # noqa: E402
from services.ledger import Ledger  # noqa: E402


class EvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="belay-evidence-boundary-")
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.evidence = self.base / "evidence"
        self.evidence.mkdir()
        self.order = "synthetic-order-7"
        self.amount = 5000
        self.journal = Journal(str(self.base / "journal.jsonl"), "boundary-test")
        intent = self.journal.append(
            "intent", slot="refund", anchor="a" * 32,
            amount=self.amount, scope="payments:refund",
        )
        self.journal.append("escalated", slot="refund", anchor="a" * 32, reason="ack lost")
        self.cutoff = intent["ts"] + 1
        self.perms = PermissionStore(str(self.base / "perms.json"))
        self.perms.grant_all(["payments:refund"])
        self.ledger = Ledger(str(self.base / "ledger.db"))
        self.addCleanup(self.ledger.close)
        self.slot = escalated_slots(str(self.base), self.order)[0]
        self.store = EvidenceStore(str(self.evidence))

    def write_source(self, name="settlement", *, records=None, outside=False):
        path = (self.base if outside else self.evidence) / f"{name}.json"
        path.write_text(json.dumps({
            "coverage": {"kind": "complete_until", "cutoff_ts": self.cutoff},
            "records": records or [],
        }), encoding="utf-8")
        return path

    def model(self, pointers, *, verdict="absent"):
        requests = []

        def transport(request, timeout):
            body = json.loads(request.data)
            requests.append(body)
            data = json.loads(body["input"][1]["content"])
            if body["text"]["format"]["name"] == "recovery_pointers":
                value = {"pointers": pointers}
            else:
                value = {
                    "verdict": verdict,
                    "citations": [obs["digest"] for obs in data["observations"]],
                    "reasoning": ["Synthetic injected conclusion"],
                }
            return json.dumps({
                "status": "completed",
                "output": [{
                    "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(value)}],
                }],
            }).encode("utf-8")

        return OpenAIRecoveryAgent(
            api_key="offline-boundary-placeholder", model="explicit-test-model",
            transport=transport,
        ), requests

    def apply(self, dossier):
        def issue_effect(amount):
            external_id = self.ledger.commit_effect("payments", "refund", self.order, amount)
            return SimpleNamespace(external_id=external_id, amount_cents=amount)

        return apply_dossier(
            dossier, journal=self.journal, perms=self.perms, issue_effect=issue_effect,
        )

    def test_model_wrong_order_prefix_cannot_duplicate_committed_refund(self):
        external_id = self.ledger.commit_effect("payments", "refund", self.order, self.amount)
        self.write_source(records=[{
            "kind": "refund", "order_id": self.order,
            "amount_cents": self.amount, "external_id": external_id,
        }])
        agent, requests = self.model([
            "settlement:manifest", f"settlement:order:{self.order}-other",
        ])
        dossier = adjudicate(self.slot, self.store, agent)
        self.assertEqual(self.apply(dossier).action, NONE)
        self.assertEqual(dossier.verdict, Verdict.ABSTAIN)
        self.assertEqual(len(self.ledger.for_order(self.order)), 1)
        self.assertEqual(len(requests), 1)
        self.assertFalse(self.journal.of_kind("adjudication_intent", "adjudicated"))

    def test_exact_absent_order_completes_once_and_replay_is_refused(self):
        self.write_source()
        pointers = ["settlement:manifest", f"settlement:order:{self.order}"]
        agent, requests = self.model(pointers)
        dossier = adjudicate(self.slot, self.store, agent)
        self.assertEqual(dossier.verdict, Verdict.ABSENT)
        self.assertEqual(self.apply(dossier).action, COMPLETED)
        self.assertEqual(self.apply(dossier).action, INCONSISTENT)
        self.assertEqual([row["amount_cents"] for row in self.ledger.for_order(self.order)], [self.amount])
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(self.journal.of_kind("adjudication_intent")), 1)

    def test_validator_rejects_prefix_query_without_adapter_guard(self):
        self.write_source()
        observations = [
            self.store.fetch(Pointer("settlement", "manifest")),
            self.store.fetch(Pointer("settlement", f"order:{self.order}-other")),
        ]
        claim = Claim("absent", [obs.digest for obs in observations])
        self.assertEqual(validate(self.slot, claim, observations).verdict, Verdict.ABSTAIN)

    def test_validator_rejects_selector_payload_disagreeing_with_pointer(self):
        self.write_source()
        manifest = self.store.fetch(Pointer("settlement", "manifest"))
        for pointer_order, payload_order in [
            (self.order + "-other", self.order),
            (self.order, self.order + "-other"),
        ]:
            with self.subTest(pointer_order=pointer_order, payload_order=payload_order):
                query = Observation(
                    Pointer("settlement", f"order:{pointer_order}"),
                    {"source": "settlement", "selector": f"order:{payload_order}", "matches": []},
                    "synthetic-observation",
                )
                claim = Claim("absent", [manifest.digest, query.digest])
                self.assertEqual(validate(self.slot, claim, [manifest, query]).verdict, Verdict.ABSTAIN)

    def test_traversal_source_is_not_resolved_or_sent_to_model(self):
        marker = "SYNTHETIC-OUTSIDE-EVIDENCE-MARKER"
        self.write_source("private", records=[{"order_id": self.order, "private_note": marker}], outside=True)
        self.assertEqual(self.store.catalog(), [])
        agent, requests = self.model([f"../private:order:{self.order}"], verdict="abstain")
        dossier = adjudicate(self.slot, self.store, agent)
        self.assertEqual(dossier.verdict, Verdict.ABSTAIN)
        self.assertEqual(dossier.pointers_resolved, 0)
        self.assertEqual(len(requests), 1)
        self.assertNotIn(marker, json.dumps(requests))

    def test_model_rejects_source_not_in_supplied_catalog(self):
        self.write_source("unlisted")
        view = self.slot.view(["settlement"])
        agent, _ = self.model(["unlisted:manifest"])
        with self.assertRaises(RecoveryModelError):
            agent.propose_pointers(view)

    def test_model_accepts_only_exact_allowed_selectors(self):
        view = self.slot.view(["settlement"])
        allowed = ["settlement:manifest", f"settlement:order:{self.order}"]
        agent, _ = self.model(allowed)
        self.assertEqual(agent.propose_pointers(view), allowed)
        for selector in [
            "manifest:extra", "anchor:" + "a" * 32, "order:",
            "order:another-order", f"order:{self.order}-other", f"order:{self.order}:extra",
        ]:
            with self.subTest(selector=selector):
                agent, _ = self.model([f"settlement:{selector}"])
                with self.assertRaises(RecoveryModelError):
                    agent.propose_pointers(view)

    def test_direct_store_rejects_traversal_and_absolute_sources(self):
        outside = self.write_source("private", outside=True)
        sources = [
            "../private", "..\\private", "./settlement", "sub/../private",
            str(outside.with_suffix("")), outside.with_suffix("").as_posix(),
            "C:\\private", "C:private", "\\\\server\\share\\private",
        ]
        self.write_source()
        for source in sources:
            with self.subTest(source=source):
                self.assertIsNone(self.store.fetch(Pointer(source, "manifest")))

    def test_valid_source_manifest_and_order_query_still_resolve(self):
        record = {"kind": "refund", "order_id": self.order, "amount_cents": self.amount, "external_id": 1}
        self.write_source(records=[record])
        self.assertEqual(self.store.catalog(), ["settlement"])
        manifest = self.store.fetch(Pointer("settlement", "manifest"))
        query = self.store.fetch(Pointer("settlement", f"order:{self.order}"))
        self.assertEqual(manifest.payload["record_count"], 1)
        self.assertEqual(query.matches, [record])

    def test_direct_store_rejects_symlink_outside_evidence_root(self):
        outside = self.write_source("private", outside=True)
        link = self.evidence / "linked.json"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"OS cannot create test symlink: {exc}")
        self.assertIsNone(self.store.fetch(Pointer("linked", "manifest")))

    def test_cached_source_cannot_be_retargeted_outside_evidence_root(self):
        outside = self.write_source("private", outside=True)
        probe = self.evidence / "probe.json"
        try:
            probe.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"OS cannot create test symlink: {exc}")
        probe.unlink()
        source = self.write_source()
        self.assertIsNotNone(self.store.fetch(Pointer("settlement", "manifest")))
        source.unlink()
        source.symlink_to(outside)
        self.assertIsNone(self.store.fetch(Pointer("settlement", "manifest")))


if __name__ == "__main__":
    unittest.main()
