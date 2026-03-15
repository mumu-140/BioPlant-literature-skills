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


class ManualReviewTest(unittest.TestCase):
    def test_apply_manual_decisions_promotes_review_to_keep(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-manual-review-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            reviewed_path = tmpdir_path / "reviewed.jsonl"
            csv_path = tmpdir_path / "review_queue.csv"
            output_path = tmpdir_path / "final_reviewed.jsonl"
            keep_path = tmpdir_path / "final_keep.jsonl"
            review_path = tmpdir_path / "final_review.jsonl"
            reject_path = tmpdir_path / "final_reject.jsonl"

            record = {
                "journal": "PNAS",
                "doi": "10.1073/example",
                "title_en": "Ambiguous example",
                "category": "other",
                "final_decision": "review",
            }
            reviewed_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["journal", "doi", "title_en", "review_final_decision", "review_final_category", "reviewer_notes"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "journal": "PNAS",
                        "doi": "10.1073/example",
                        "title_en": "Ambiguous example",
                        "review_final_decision": "keep",
                        "review_final_category": "methods-datasets-resources",
                        "reviewer_notes": "Codex confirmed relevance",
                    }
                )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "apply_manual_decisions.py"),
                    "--input",
                    str(reviewed_path),
                    "--decisions-csv",
                    str(csv_path),
                    "--output",
                    str(output_path),
                    "--keep-output",
                    str(keep_path),
                    "--review-output",
                    str(review_path),
                    "--reject-output",
                    str(reject_path),
                ],
                check=True,
                cwd=SKILL_DIR,
            )

            keep_records = [json.loads(line) for line in keep_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(keep_records), 1)
            self.assertEqual(keep_records[0]["final_decision"], "keep")
            self.assertEqual(keep_records[0]["category"], "methods-datasets-resources")
