"""Offline tests of the model boundary. No API credentials or calls needed."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from second.adjudicate import EscalatedSlot, adjudicate  # noqa: E402
from second.dossier import Verdict  # noqa: E402
from second.evidence import EvidenceStore, Observation, Pointer  # noqa: E402
from second.live_agent import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    OpenAIRecoveryAgent,
    RecoveryModelError,
)

KEY = "sk-offline-fixture-secret-123456"
VIEW = {"anchor": "a" * 32, "slot": "refund", "order_id": "synthetic-order",
        "amount_cents": 5000, "intent_ts": 1000.0,
        "escalation_reason": "ack lost", "evidence_sources_available": ["settlement"]}


def response(value=None, *, content=None, status="completed", usage=True) -> bytes:
    doc = {
        "status": status,
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": content if content is not None else [
                        {"type": "output_text", "text": json.dumps(value)}]}],
    }
    if usage:
        doc["usage"] = {"input_tokens": 100, "output_tokens": 20}
    return json.dumps(doc).encode()


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class LiveAgentTests(unittest.TestCase):
    def agent(self, *responses, **kwargs):
        transport = FakeTransport(*responses)
        return OpenAIRecoveryAgent(api_key=KEY, model="explicit-test-model", transport=transport, **kwargs), transport

    def test_strict_request_and_minimal_inputs(self):
        agent, transport = self.agent(response({"pointers": ["settlement:manifest"]}))
        self.assertEqual(agent.propose_pointers({**VIEW, "private_field": "must-stay-local"}), ["settlement:manifest"])
        request, timeout = transport.requests[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(timeout, 30)
        self.assertFalse(body["store"])
        self.assertEqual(body["max_output_tokens"], 1200)
        self.assertEqual(body["model"], "explicit-test-model")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertFalse(body["text"]["format"]["schema"]["additionalProperties"])
        self.assertNotIn("must-stay-local", request.data.decode())
        self.assertNotIn(KEY, request.data.decode())

    def test_conclusion_schema_cannot_set_amount_or_permission(self):
        agent, transport = self.agent(response({"verdict": "abstain", "citations": [], "reasoning": ["No coverage"]}))
        obs = Observation(Pointer("settlement", "manifest"), {"source": "settlement"}, "private/path/report.json")
        claim = agent.conclude(VIEW, [obs])
        self.assertEqual(claim.verdict, "abstain")
        request = json.loads(transport.requests[0][0].data)
        self.assertEqual(set(request["text"]["format"]["schema"]["properties"]), {"verdict", "citations", "reasoning"})
        self.assertNotIn("private/path", json.dumps(request))
        self.assertIn(obs.digest, json.dumps(request))

    def test_metrics_are_measured_and_mock_labelled(self):
        agent, _ = self.agent(response({"pointers": []}), input_price_per_million=2, output_price_per_million=3)
        agent.propose_pointers(VIEW)
        metrics = agent.metrics()
        self.assertEqual(metrics["transport"], "mock")
        self.assertEqual(metrics["requests"], 1)
        self.assertEqual(metrics["input_tokens"], 100)
        self.assertEqual(metrics["output_tokens"], 20)
        self.assertEqual(metrics["usage_responses"], 1)
        self.assertGreaterEqual(metrics["latency_ms"], 0)
        self.assertAlmostEqual(metrics["estimated_cost_usd"], 0.00026)
        self.assertNotIn(KEY, json.dumps(metrics))
        self.assertNotIn(KEY, repr(agent))

    def test_unknown_usage_or_prices_never_invents_cost(self):
        for kwargs, has_usage in [({}, True), ({"input_price_per_million": 1, "output_price_per_million": 1}, False)]:
            agent, _ = self.agent(response({"pointers": []}, usage=has_usage), **kwargs)
            agent.propose_pointers(VIEW)
            self.assertIsNone(agent.metrics()["estimated_cost_usd"])

    def test_from_env_requires_explicit_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                OpenAIRecoveryAgent.from_env()
        with patch.dict(os.environ, {"OPENAI_API_KEY": KEY}, clear=True):
            with self.assertRaisesRegex(ValueError, "explicit model"):
                OpenAIRecoveryAgent.from_env()
        with patch.dict(os.environ, {"OPENAI_API_KEY": KEY, "OPENAI_MODEL": "env-model"}, clear=True):
            self.assertEqual(OpenAIRecoveryAgent.from_env().model, "env-model")
            self.assertEqual(OpenAIRecoveryAgent.from_env(model="cli-model").model, "cli-model")

    def test_request_budget_and_input_bounds(self):
        agent, transport = self.agent(response({"pointers": []}), response({"pointers": []}))
        agent.propose_pointers(VIEW)
        agent.propose_pointers(VIEW)
        with self.assertRaisesRegex(RecoveryModelError, "request_budget_exhausted"):
            agent.propose_pointers(VIEW)
        self.assertEqual(len(transport.requests), 2)
        agent, transport = self.agent()
        with self.assertRaisesRegex(RecoveryModelError, "input_too_large"):
            agent.propose_pointers({**VIEW, "escalation_reason": "x" * 70000})
        self.assertFalse(transport.requests)

    def test_refusal_incomplete_malformed_and_transport_errors(self):
        broken = [
            (response(content=[{"type": "refusal", "refusal": "no"}]), "refusal"),
            (response({"pointers": []}, status="incomplete"), "response_not_completed"),
            (b"not JSON", "invalid_response_json"),
            (b"[]", "invalid_response_shape"),
            (response(content=[]), "invalid_output_size"),
            (response(content=[{"type": "output_text", "text": "{bad"}]), "invalid_output_json"),
            (response(content=[{"type": "output_text", "text": "\ud800" + KEY}]), "invalid_output_encoding"),
            (response(content=[{"type": "output_text", "text": '{"pointers":[],"pointers":[]}'}]), "invalid_output_json"),
            (b" " * (MAX_RESPONSE_BYTES + 1), "invalid_response_size"),
            (TimeoutError("remote failure " + KEY), "transport_error"),
            (urllib.error.HTTPError("https://api.openai.com", 401, KEY, {}, None), "http_error"),
        ]
        for raw, code in broken:
            with self.subTest(code=code):
                agent, _ = self.agent(raw)
                with self.assertRaisesRegex(RecoveryModelError, code) as raised:
                    agent.propose_pointers(VIEW)
                self.assertNotIn(KEY, repr(raised.exception))
                self.assertEqual(agent.metrics()["errors"], {code: 1})

    def test_schema_shapes_and_oversized_fields_fail_closed(self):
        for value in [[], {"pointers": "a"}, {"pointers": [None]}, {"pointers": ["a"] * 17},
                      {"pointers": ["x" * 257]}, {"pointers": [], "amount": 100}]:
            agent, _ = self.agent(response(value))
            with self.subTest(value=value), self.assertRaises(RecoveryModelError):
                agent.propose_pointers(VIEW)
        for value in [
            {"verdict": "absent", "citations": [], "reasoning": [], "amount": 1},
            {"verdict": "certain", "citations": [], "reasoning": []},
            {"verdict": "absent", "citations": [None], "reasoning": []},
            {"verdict": "absent", "citations": [], "reasoning": ["x" * 1001]},
            {"verdict": "absent", "citations": [], "reasoning": ["x"] * 5},
        ]:
            agent, _ = self.agent(response(value))
            with self.subTest(value=value), self.assertRaises(RecoveryModelError):
                agent.conclude(VIEW, [])

    def test_key_echo_and_key_in_input_are_redacted(self):
        agent, _ = self.agent(response({"verdict": "abstain", "citations": [], "reasoning": [KEY]}))
        with self.assertRaisesRegex(RecoveryModelError, "credential_in_output"):
            agent.conclude(VIEW, [])
        agent, transport = self.agent()
        with self.assertRaisesRegex(RecoveryModelError, "credential_in_input"):
            agent.propose_pointers({**VIEW, "escalation_reason": KEY})
        self.assertEqual(transport.requests, [])

    def test_pipeline_converts_provider_errors_and_fabrication_to_abstention(self):
        with tempfile.TemporaryDirectory() as directory:
            esc = EscalatedSlot(VIEW["anchor"], "refund", VIEW["order_id"], 5000,
                                "payments:refund", 1000.0, "ack lost")
            store = EvidenceStore(directory)
            for raw in [TimeoutError(KEY), response({"pointers": ["missing:manifest"]})]:
                agent, _ = self.agent(raw, response({"verdict": "absent", "citations": ["fabricated"], "reasoning": ["I guessed"]}))
                dossier = adjudicate(esc, store, agent)
                self.assertEqual(dossier.verdict, Verdict.ABSTAIN)
                self.assertNotIn(KEY, json.dumps(dossier.as_dict()))

    def test_real_verifier_accepts_valid_mocked_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "settlement.json").write_text(json.dumps({
                "coverage": {"kind": "complete_until", "cutoff_ts": 2000},
                "records": [{"kind": "refund", "order_id": VIEW["order_id"], "amount_cents": 5000, "external_id": 1}],
            }), encoding="utf-8")
            store = EvidenceStore(directory)
            obs = store.fetch(Pointer("settlement", "order:" + VIEW["order_id"]))
            agent, _ = self.agent(
                response({"pointers": [str(obs.pointer)]}),
                response({"verdict": "committed", "citations": [obs.digest], "reasoning": ["Matching refund record"]}),
            )
            esc = EscalatedSlot(VIEW["anchor"], "refund", VIEW["order_id"], 5000,
                                "payments:refund", 1000.0, "ack lost")
            dossier = adjudicate(esc, store, agent)
            self.assertEqual(dossier.verdict, Verdict.COMMITTED)
            self.assertEqual(dossier.amount_cents, 5000)


if __name__ == "__main__":
    unittest.main()
