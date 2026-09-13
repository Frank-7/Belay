"""Publication boundaries: authentic evidence, contained output, complete builds."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_site as builder  # noqa: E402


def records() -> tuple[dict, dict, dict]:
    findings = {
        "n_crashes_confirmed": 2,
        "runtimes": {"anchored": {
            "trials": 2, "violations": 0,
            "verdicts": {"clean": 1, "escalated": 1},
        }},
    }
    matrix = {
        "config": {
            "runtimes": ["anchored"], "tiers": ["opaque"],
            "crash_points": ["after_intent"], "reps": 1,
        },
        "trials": [
            {"runtime": "anchored", "verdict": "clean", "crashed_as_asked": True},
            {"runtime": "anchored", "verdict": "escalated",
             "crashed_as_asked": True},
        ],
    }
    adjudication = {
        "summary": {
            "cases": 3,
            "by_pipeline": {"validated": {"resolved": 1, "abstained": 1}},
            "validated": {"cases": 2, "resolved": 1},
        },
        "cases": [
            {"pipeline": "validated", "grade": "resolved"},
            {"pipeline": "validated", "grade": "abstained"},
            {"pipeline": "trusting", "grade": "false"},
        ],
    }
    return findings, matrix, adjudication


def site_html() -> str:
    fields = (
        "crashes", "violations", "trials", "resolved", "adjudications",
    )
    numbers = "".join(f'<span id="metric-{field}">999</span>' for field in fields)
    sources = "".join(
        f'<a data-source="{source}" href="https://github.com/Frank-7/Belay/blob/main/README.md">Source</a>'
        for source in ("matrix", "findings", "adjudication", "writeup", "contract")
    )
    return (
        '<!doctype html><a href="recovery-desk.html">Recovery Desk</a>'
        + numbers
        + '<p><span id="metric-false">0</span> false resolutions in this recorded set. '
        'The remaining <span id="metric-abstained">110</span> cases stayed unresolved.</p>'
        + sources
    )


class EvidenceTests(unittest.TestCase):
    def evidence(self, data=None):
        return builder.evidence_from_records(
            *(data or records()), "a" * 40, "Frank-7/Belay",
        )

    def test_scoped_counts_and_commit_pinned_sources(self):
        evidence = self.evidence()
        self.assertEqual(evidence["metrics"]["crash_trials"]["confirmed"], 2)
        self.assertEqual(evidence["metrics"]["anchored"]["trials"], 2)
        self.assertEqual(evidence["metrics"]["adjudication"]["trials"], 2)
        self.assertEqual(evidence["metrics"]["adjudication"]["false_resolutions"], 0)
        self.assertEqual(evidence["metrics"]["adjudication"]["resolved"], 1)
        self.assertIn("not production failure rates", evidence["scope"])
        for url in evidence["sources"].values():
            self.assertIn("/blob/" + "a" * 40 + "/", url)

    def test_nonzero_observation_is_not_replaced_with_a_marketing_zero(self):
        findings, matrix, adjudication = records()
        matrix["trials"][0]["verdict"] = "duplicate_effect"
        findings["runtimes"]["anchored"].update({
            "violations": 1, "verdicts": {"duplicate_effect": 1, "escalated": 1},
        })
        adjudication["cases"][0]["grade"] = "false"
        adjudication["summary"]["by_pipeline"]["validated"] = {
            "false": 1, "abstained": 1,
        }
        adjudication["summary"]["validated"]["resolved"] = 0
        evidence = self.evidence((findings, matrix, adjudication))
        self.assertEqual(evidence["metrics"]["anchored"]["violations"], 1)
        self.assertEqual(evidence["metrics"]["adjudication"]["false_resolutions"], 1)

    def test_refuses_incomplete_crashes_and_disagreeing_summaries(self):
        changes = [
            lambda f, m, a: m["trials"][0].update(crashed_as_asked=False),
            lambda f, m, a: m["config"].update(reps=2),
            lambda f, m, a: f.update(n_crashes_confirmed=960),
            lambda f, m, a: f["runtimes"]["anchored"].update(trials=240),
            lambda f, m, a: m["trials"][0].update(verdict="duplicate_effect"),
            lambda f, m, a: m["trials"][0].update(verdict="new_undefined_outcome"),
            lambda f, m, a: a["cases"][0].update(grade="false"),
            lambda f, m, a: a["summary"].update(cases=200),
            lambda f, m, a: a["summary"]["validated"].update(cases=200),
        ]
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                data = copy.deepcopy(records())
                change(*data)
                with self.assertRaises(ValueError):
                    self.evidence(data)

    def test_reads_evidence_from_git_objects_not_mutable_result_files(self):
        sha = "b" * 40
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "results").mkdir()
            (root / "results" / "findings.json").write_text(
                "uncommitted experiment output", encoding="utf-8",
            )
            with patch.object(
                builder.subprocess, "check_output",
                side_effect=[sha + "\n"] + [json.dumps(d).encode() for d in records()],
            ) as git:
                evidence = builder.committed_evidence(root, "Frank-7/Belay")
        self.assertEqual(evidence["source_commit"], sha)
        self.assertEqual(evidence["metrics"]["crash_trials"]["confirmed"], 2)
        for call in git.call_args_list[1:]:
            self.assertEqual(call.args[0][-2], "show")
            self.assertTrue(call.args[0][-1].startswith(sha + ":results/"))

    def test_metric_binding_requires_exactly_one_field_and_known_sources(self):
        malformed = (
            site_html().replace('id="metric-false"', 'id="missing"'),
            site_html() + '<span id="metric-false">0</span>',
            site_html().replace('id="metric-false">0', 'id="metric-false"><b>0</b>'),
            site_html().replace('data-source="matrix"', 'data-source="unknown"'),
        )
        for html in malformed:
            with self.subTest(html=html), self.assertRaises(ValueError):
                builder.bind_evidence(html, self.evidence())


class BuildBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "site").mkdir()
        (self.root / "site" / "index.html").write_text(
            site_html(), encoding="utf-8",
        )
        (self.root / "site" / "assets").mkdir()
        (self.root / "site" / "assets" / "app.js").write_text(
            "/* local asset */", encoding="utf-8",
        )
        (self.root / "site" / "assets" / "favicon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8",
        )
        self.evidence = builder.evidence_from_records(
            *records(), "c" * 40, "Frank-7/Belay",
        )
        self.provenance = patch.object(
            builder, "committed_evidence", return_value=self.evidence,
        )
        self.provenance.start()
        self.addCleanup(self.provenance.stop)

    def render(self, command, **kwargs):
        self.assertEqual(command[1], str(self.root / "viewer" / "build_viewer.py"))
        self.assertEqual(command[2], "--out")
        self.assertTrue(kwargs["check"])
        Path(command[3]).write_text(
            "<!doctype html><html><head></head><body>recorded demo</body></html>",
            encoding="utf-8",
        )

    def build(self, path=Path("_site")):
        with patch.object(builder.subprocess, "run", side_effect=self.render):
            return builder.build_site(self.root, path, "Frank-7/Belay")

    def test_complete_build_and_rebuild_remove_stale_assets(self):
        output = self.build()
        self.assertTrue((output / "recovery-desk.html").is_file())
        self.assertIn('href="assets/favicon.svg"',
                      (output / "recovery-desk.html").read_text(encoding="utf-8"))
        self.assertTrue((output / "assets" / "app.js").is_file())
        self.assertEqual(
            json.loads((output / "evidence.json").read_text(encoding="utf-8")),
            self.evidence,
        )
        self.assertFalse((output / "results").exists())
        (output / "stale.txt").write_text("old build asset", encoding="utf-8")
        self.build()
        self.assertFalse((output / "stale.txt").exists())

    def test_published_html_binds_changed_outcomes_and_pins_links_without_javascript(self):
        self.evidence["metrics"]["adjudication"].update(
            false_resolutions=2, resolved=3, abstained=5, trials=10,
        )
        output = self.build()
        page = (output / "index.html").read_text(encoding="utf-8")
        self.assertIn('<span id="metric-false">2</span> false resolutions', page)
        self.assertIn('remaining <span id="metric-abstained">5</span>', page)
        self.assertIn('<span id="metric-adjudications">10</span>', page)
        self.assertIn('<span id="metric-crashes">2</span>', page)
        self.assertNotIn("/blob/main/", page)
        for url in self.evidence["sources"].values():
            self.assertIn(f'href="{url}"', page)

    def test_failed_viewer_keeps_previous_build_and_cleans_staging(self):
        output = self.build(Path("tmp-runs/preview"))
        old = (output / "index.html").read_bytes()
        (self.root / "site" / "index.html").write_text(
            site_html() + "new page", encoding="utf-8",
        )
        with patch.object(
            builder.subprocess, "run", side_effect=subprocess.CalledProcessError(1, []),
        ), self.assertRaises(subprocess.CalledProcessError):
            builder.build_site(self.root, output, "Frank-7/Belay")
        self.assertEqual((output / "index.html").read_bytes(), old)
        self.assertEqual(list(output.parent.glob(".pages-build-*")), [])

    def test_missing_assets_and_root_relative_links_cannot_replace_a_good_build(self):
        output = self.build()
        original = (output / "index.html").read_bytes()
        for target in ("assets/missing.js", "/assets/app.js", "../private.txt"):
            (self.root / "site" / "index.html").write_text(
                site_html() + f'<script src="{target}"></script>', encoding="utf-8",
            )
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.build()
            self.assertEqual((output / "index.html").read_bytes(), original)

    def test_refuses_output_outside_dedicated_build_directories(self):
        for path in (".", "site", "results", ".git", "tmp-runs", "../outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                builder.output_path(self.root, Path(path))
        self.assertTrue((self.root / "site" / "index.html").is_file())

    def test_refuses_to_replace_an_unmarked_existing_directory(self):
        output = self.root / "tmp-runs" / "precious"
        output.mkdir(parents=True)
        (output / "keep.txt").write_text("keep me", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-build directory"):
            self.build(output)
        self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "keep me")

    def test_hidden_and_generated_source_files_cannot_be_published(self):
        for name in (".env", "evidence.json", "recovery-desk.html"):
            asset = self.root / "site" / name
            asset.write_text("not a public site asset", encoding="utf-8")
            try:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.build()
                self.assertFalse((self.root / "_site").exists())
            finally:
                asset.unlink()

    def test_source_symlink_does_not_copy_non_site_content(self):
        private = self.root / "private.txt"
        private.write_text("not for publishing", encoding="utf-8")
        link = self.root / "site" / "linked.txt"
        try:
            link.symlink_to(private)
        except OSError:
            self.skipTest("creating symlinks is unavailable on this host")
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            self.build()
        self.assertFalse((self.root / "_site").exists())

    def test_output_symlink_cannot_replace_another_directory(self):
        target = self.root / "site"
        try:
            (self.root / "_site").symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("creating symlinks is unavailable on this host")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.build()
        self.assertTrue((target / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
