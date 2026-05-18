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


class ReviewBacklogTest(unittest.TestCase):
    def test_finalize_review_backlog_archives_optimized_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-backlog-") as tmpdir:
            backlog_dir = Path(tmpdir) / "backlog"
            backlog_dir.mkdir(parents=True)
            csv_path = backlog_dir / "review_backlog.csv"
            html_path = backlog_dir / "review_backlog.html"
            xlsx_path = backlog_dir / "review_backlog.xlsx"
            state_path = backlog_dir / "review_backlog_state.json"
            selection_path = backlog_dir / "optimization_selection.json"

            fieldnames = [
                "digest_date",
                "review_status",
                "reviewed_at",
                "optimized_at",
                "archived_at",
                "last_manual_edit_hash",
                "source_review_file",
                "source_id",
                "journal",
                "publish_date",
                "publication_stage",
                "category",
                "interest_level",
                "interest_level_options",
                "interest_tag",
                "interest_tag_options",
                "title_en",
                "title_zh",
                "summary_zh",
                "abstract",
                "doi",
                "article_url",
                "tags",
                "llm_decision",
                "llm_confidence",
                "llm_reason",
                "review_final_decision",
                "review_final_decision_options",
                "review_final_category",
                "review_final_category_options",
                "reviewer_notes",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "digest_date": "2026-03-17",
                        "review_status": "optimized",
                        "optimized_at": "2026-03-17T08:30:00Z",
                        "source_review_file": str(
                            SKILL_DIR / "var" / "reviews" / "daily-reviews" / "2026-03-17" / "daily_review.xlsx"
                        ),
                        "source_id": "nature",
                        "journal": "Nature",
                        "publication_stage": "journal",
                        "category": "plant-biology",
                        "interest_level": "非常感兴趣",
                        "interest_tag": "生物通络",
                        "title_en": "Consumed row",
                    }
                )
                writer.writerow(
                    {
                        "digest_date": "2026-03-17",
                        "review_status": "pending_review",
                        "source_review_file": str(
                            SKILL_DIR / "var" / "reviews" / "daily-reviews" / "2026-03-17" / "daily_review.xlsx"
                        ),
                        "source_id": "science",
                        "journal": "Science",
                        "publication_stage": "journal",
                        "category": "omics",
                        "interest_level": "感兴趣",
                        "interest_tag": "组学",
                        "title_en": "Pending row",
                    }
                )
            html_path.write_text("placeholder", encoding="utf-8")
            xlsx_path.write_bytes(b"placeholder")
            state_path.write_text("{}", encoding="utf-8")
            selection_path.write_text('{"selected_rows":[{"digest_date":"2026-03-17","key_kind":"doi","key_value":"10.1/demo"}]}\n', encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "review_backlog.py"),
                    "finalize",
                    "--backlog-dir",
                    str(backlog_dir),
                ],
                check=True,
                cwd=SKILL_DIR,
            )

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title_en"], "Pending row")

            archive_root = backlog_dir / "archive" / "2026-03-17"
            batch_csv_files = list(archive_root.glob("optimized_batch_*.csv"))
            self.assertEqual(len(batch_csv_files), 1)
            batch_selection_files = list(archive_root.glob("optimized_batch_*.selection.json"))
            self.assertEqual(len(batch_selection_files), 1)
            self.assertFalse(selection_path.exists())
            with batch_csv_files[0].open("r", encoding="utf-8", newline="") as handle:
                archived_rows = list(csv.DictReader(handle))
            self.assertEqual(len(archived_rows), 1)
            self.assertEqual(archived_rows[0]["title_en"], "Consumed row")

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["active_counts"]["pending_review"], 1)
            self.assertEqual(state["archived_now"], 1)
            self.assertTrue(state["archived_selection_json"].endswith(".selection.json"))


if __name__ == "__main__":
    unittest.main()
