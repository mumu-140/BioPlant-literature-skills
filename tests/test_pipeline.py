#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
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
            metadata_path = run_dir / "run_metadata.json"
            rejected_path = run_dir / "rejected_records.jsonl"
            localized_path = run_dir / "localized_records.jsonl"
            review_queue_csv = run_dir / "review_queue.csv"
            feedback_report = run_dir / "rule_feedback_report.md"
            daily_review_csv = run_dir / "daily_review.csv"
            daily_review_html = run_dir / "daily_review.html"
            daily_review_xlsx = run_dir / "daily_review.xlsx"

            self.assertTrue(csv_path.exists())
            self.assertTrue(html_path.exists())
            self.assertTrue(xlsx_path.exists())
            self.assertTrue(metadata_path.exists())
            self.assertTrue(review_queue_csv.exists())
            self.assertTrue(feedback_report.exists())
            self.assertTrue(daily_review_csv.exists())
            self.assertTrue(daily_review_html.exists())
            self.assertTrue(daily_review_xlsx.exists())

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "success")
            self.assertEqual(metadata["email_status"], "skipped")
            self.assertEqual(metadata["counts"]["digest_csv_rows"], 3)
            self.assertEqual(metadata["counts"]["review_queue_csv_rows"], 0)
            self.assertEqual(metadata["counts"]["daily_review_csv_rows"], 3)
            self.assertEqual(metadata["window"]["start_utc"], "2026-03-13T00:00:00Z")
            self.assertEqual(metadata["window"]["end_utc"], "2026-03-15T00:00:00Z")
            self.assertTrue(metadata["artifacts"]["digest_csv"]["exists"])
            self.assertTrue(metadata["artifacts"]["daily_review_csv"]["exists"])

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertIn("interest_level", rows[0])
            self.assertIn("interest_tag", rows[0])
            self.assertTrue(all(row["publish_date"].endswith("+08:00") for row in rows))
            self.assertEqual(
                {row["category"] for row in rows},
                {"omics", "ai-computational-biology", "methods-datasets-resources"},
            )
            self.assertIn("A single-cell atlas of rice root development", {row["title_en"] for row in rows})
            self.assertEqual({row["publication_stage"] for row in rows}, {"journal", "preprint"})

            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("Daily Bio Literature Digest", html_text)
            self.assertIn("Preprints", html_text)
            self.assertIn("card-title", html_text)
            self.assertIn("点击展开阅读摘要", html_text)
            self.assertIn("DOI:", html_text)
            self.assertIn("interest-stars", html_text)
            self.assertIn("bioRxiv (Genomics And Bioinformatics)", html_text)
            self.assertIn("Nature Methods", html_text)
            self.assertIn("按期刊分组，默认折叠", html_text)
            self.assertIn("Asia/Shanghai", html_text)

            with daily_review_csv.open("r", encoding="utf-8", newline="") as handle:
                review_rows = list(csv.DictReader(handle))
            self.assertEqual(len(review_rows), 3)
            self.assertIn("interest_level_options", review_rows[0])
            self.assertIn("interest_tag_options", review_rows[0])
            self.assertIn("review_final_decision_options", review_rows[0])
            self.assertIn("review_final_category_options", review_rows[0])
            self.assertIn("非常感兴趣", review_rows[0]["interest_level_options"])
            self.assertIn("模型", review_rows[0]["interest_tag_options"])
            self.assertIn("keep", review_rows[0]["review_final_decision_options"])
            self.assertIn("plant-biology", review_rows[0]["review_final_category_options"])

            daily_review_html_text = daily_review_html.read_text(encoding="utf-8")
            self.assertIn("导出审核 CSV", daily_review_html_text)
            self.assertIn("<select data-column=\"interest_level\">", daily_review_html_text)

            with zipfile.ZipFile(daily_review_xlsx) as archive:
                sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            self.assertIn("dataValidation", sheet_xml)
            self.assertIn("&quot;仅保留,非常一般,一般,感兴趣,非常感兴趣&quot;", sheet_xml)
            self.assertIn("&quot;keep,review,reject&quot;", sheet_xml)

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
