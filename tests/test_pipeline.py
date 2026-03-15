#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_raw.jsonl"


class PipelineTest(unittest.TestCase):
    maxDiff = None

    def test_dry_run_pipeline_exports_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-digest-test-") as tmpdir:
            run_dir = Path(tmpdir) / "run"
            command = [
                sys.executable,
                str(SCRIPTS_DIR / "run_digest.py"),
                "--work-dir",
                str(run_dir),
                "--input-file",
                str(FIXTURE_PATH),
                "--skip-email",
                "--summary-provider",
                "placeholder",
                "--window-start",
                "2026-03-13T00:00:00Z",
                "--window-end",
                "2026-03-15T00:00:00Z",
            ]
            subprocess.run(command, check=True, cwd=SKILL_DIR)

            csv_path = run_dir / "digest.csv"
            html_path = run_dir / "digest.html"
            xlsx_path = run_dir / "digest.xlsx"
            rejected_path = run_dir / "rejected_records.jsonl"
            localized_path = run_dir / "localized_records.jsonl"
            review_queue_csv = run_dir / "review_queue.csv"
            feedback_report = run_dir / "rule_feedback_report.md"

            self.assertTrue(csv_path.exists())
            self.assertTrue(html_path.exists())
            self.assertTrue(xlsx_path.exists())
            self.assertTrue(review_queue_csv.exists())
            self.assertTrue(feedback_report.exists())

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertEqual(
                {row["category"] for row in rows},
                {"plant-biology", "ai-computational-biology", "methods-datasets-resources"},
            )
            self.assertIn("A single-cell atlas of rice root development", {row["title_en"] for row in rows})
            self.assertEqual({row["publication_stage"] for row in rows}, {"journal", "preprint"})

            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("Daily Bio Literature Digest", html_text)
            self.assertIn("Preprints", html_text)
            self.assertIn("card-title", html_text)
            self.assertIn("点击展开阅读摘要", html_text)
            self.assertIn("DOI:", html_text)
            self.assertIn("bioRxiv (Genomics And Bioinformatics)", html_text)
            self.assertIn("Nature Methods", html_text)
            self.assertIn("按期刊分组，默认折叠", html_text)

            rejected_records = [
                json.loads(line)
                for line in rejected_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rejected_records), 1)
            self.assertEqual(rejected_records[0]["journal"], "Science Advances")

            localized_records = [
                json.loads(line)
                for line in localized_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(localized_records), 3)
            for record in localized_records:
                self.assertIn("summary_zh", record)
                self.assertIn("title_zh", record)
                self.assertTrue(record["summary_zh"])
            self.assertTrue(any("预印本" in record["summary_zh"] for record in localized_records if record["publication_stage"] == "preprint"))

            report_text = feedback_report.read_text(encoding="utf-8")
            self.assertIn("Rule Feedback Report", report_text)


if __name__ == "__main__":
    unittest.main()
