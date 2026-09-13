"""Frozen constructed boundary suite; no model or payment network calls."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.recovery_holdout import run_holdout  # noqa: E402


class HoldoutTests(unittest.TestCase):
    def test_frozen_cases_and_expected_outcomes(self):
        report = run_holdout()
        self.assertEqual(report["authoring_seed"], 20260913)
        self.assertEqual(report["fixture_sha256"], "c45e7adf05348c7abdd0bf722d987ed89b4a3bb6aba9a9434bb6fdc06afc0f5b")
        self.assertEqual(report["summary"]["unique_cases"], 12)
        self.assertEqual(report["summary"]["correct"], 12)
        self.assertEqual(report["summary"]["false_resolutions"], 0)
        self.assertEqual(report["summary"]["verdicts"], {"committed": 2, "absent": 2, "abstain": 8})
        self.assertEqual(report["summary"]["live_model_requests"], 0)
        self.assertEqual(report["execution"], "classification_only_no_effect_issuer")

    def test_repeated_cases_are_not_counted_as_new_holdout_cases(self):
        report = run_holdout(repeats=2)
        self.assertEqual(report["summary"]["unique_cases"], 12)
        self.assertEqual(report["summary"]["samples"], 24)
        for first, second in zip(report["cases"][:12], report["cases"][12:], strict=True):
            self.assertEqual(first["fixture_digest"], second["fixture_digest"])
            self.assertEqual(first["verdict"], second["verdict"])
        self.assertIn("not fresh", report["status"])

    def test_run_bounds(self):
        for repeats in (0, 6, True):
            with self.subTest(repeats=repeats), self.assertRaises(ValueError):
                run_holdout(repeats=repeats)


if __name__ == "__main__":
    unittest.main()
