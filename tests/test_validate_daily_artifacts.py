#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_daily_artifacts import validate_run_dir


class ValidateDailyArtifactsTest(unittest.TestCase):
    def test_validate_run_dir_accepts_successful_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-validate-") as tmpdir:
            run_dir = Path(tmpdir)
            for filename in [
                "digest.html",
                "digest.xlsx",
                "review_queue.html",
                "review_queue.xlsx",
            ]:
                (run_dir / filename).write_text("ok", encoding="utf-8")
            (run_dir / "digest.csv").write_text("title_en\npaper a\n", encoding="utf-8")
            (run_dir / "review_queue.csv").write_text("title_en\n", encoding="utf-8")
            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "status": "success",
                        "failed_step": None,
                        "failure_message": None,
                        "window": {
                            "start_utc": "2026-03-15T00:00:00Z",
                            "end_utc": "2026-03-16T00:00:00Z",
                        },
                        "counts": {
                            "digest_csv_rows": 1,
                            "review_queue_csv_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = validate_run_dir(run_dir)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["issues"], [])
            self.assertEqual(result["warnings"], [])

    def test_validate_run_dir_flags_failed_run_and_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-validate-") as tmpdir:
            run_dir = Path(tmpdir)
            (run_dir / "digest.csv").write_text("title_en\n", encoding="utf-8")
            (run_dir / "review_queue.csv").write_text("title_en\n", encoding="utf-8")
            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "failed_step": "send_email",
                        "failure_message": "dns failed",
                        "window": {
                            "start_utc": "2026-03-15T00:00:00Z",
                            "end_utc": "2026-03-16T00:00:00Z",
                        },
                        "counts": {
                            "digest_csv_rows": 0,
                            "review_queue_csv_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = validate_run_dir(run_dir)

            self.assertEqual(result["status"], "error")
            self.assertTrue(any("Missing core artifact" in issue for issue in result["issues"]))
            self.assertTrue(any("send_email" in issue for issue in result["issues"]))

    def test_validate_run_dir_warns_on_empty_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-validate-") as tmpdir:
            run_dir = Path(tmpdir)
            for filename in [
                "digest.html",
                "digest.xlsx",
                "review_queue.html",
                "review_queue.xlsx",
            ]:
                (run_dir / filename).write_text("ok", encoding="utf-8")
            (run_dir / "digest.csv").write_text("title_en\n", encoding="utf-8")
            (run_dir / "review_queue.csv").write_text("title_en\n", encoding="utf-8")
            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "status": "success",
                        "failed_step": None,
                        "failure_message": None,
                        "window": {
                            "start_utc": "2026-03-15T00:00:00Z",
                            "end_utc": "2026-03-16T00:00:00Z",
                        },
                        "counts": {
                            "digest_csv_rows": 0,
                            "review_queue_csv_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = validate_run_dir(run_dir)

            self.assertEqual(result["status"], "warning")
            self.assertTrue(any("digest.csv contains 0 data rows" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
