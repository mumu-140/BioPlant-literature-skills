#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"


class LlmReviewTest(unittest.TestCase):
    def test_placeholder_review_routes_other_to_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-llm-review-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "classified.jsonl"
            reviewed_path = tmpdir_path / "reviewed.jsonl"
            keep_path = tmpdir_path / "keep.jsonl"
            review_path = tmpdir_path / "review.jsonl"
            reject_path = tmpdir_path / "reject.jsonl"
            records = [
                {
                    "journal": "Cell",
                    "source_id": "cell",
                    "title_en": "A cell atlas of maize roots",
                    "category": "plant-biology",
                    "publication_stage": "journal",
                    "relevance_status": "keep",
                    "abstract": "A plant single-cell atlas study.",
                    "tags": ["plant", "single-cell"],
                },
                {
                    "journal": "PNAS",
                    "source_id": "pnas",
                    "title_en": "A challenging ambiguous behavior study",
                    "category": "other",
                    "publication_stage": "journal",
                    "relevance_status": "keep",
                    "abstract": "Ambiguous biology relevance.",
                    "tags": [],
                },
            ]
            input_path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "llm_review.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(reviewed_path),
                    "--keep-output",
                    str(keep_path),
                    "--review-output",
                    str(review_path),
                    "--reject-output",
                    str(reject_path),
                    "--provider",
                    "placeholder",
                ],
                check=True,
                cwd=SKILL_DIR,
            )
            keep_records = [json.loads(line) for line in keep_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            review_records = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(keep_records), 1)
            self.assertEqual(len(review_records), 1)
            self.assertEqual(review_records[0]["llm_decision"], "review")

    def test_placeholder_review_keeps_other_when_strong_bio_signal_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-llm-review-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "classified.jsonl"
            reviewed_path = tmpdir_path / "reviewed.jsonl"
            keep_path = tmpdir_path / "keep.jsonl"
            review_path = tmpdir_path / "review.jsonl"
            reject_path = tmpdir_path / "reject.jsonl"
            records = [
                {
                    "journal": "Nature Communications",
                    "source_id": "nature-communications",
                    "title_en": "Diversification of functional requirements for proteolysis of auxin response factors",
                    "category": "other",
                    "publication_stage": "journal",
                    "relevance_status": "keep",
                    "abstract": "This study dissects auxin response factor proteolysis in plants.",
                    "tags": [],
                },
            ]
            input_path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "llm_review.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(reviewed_path),
                    "--keep-output",
                    str(keep_path),
                    "--review-output",
                    str(review_path),
                    "--reject-output",
                    str(reject_path),
                    "--provider",
                    "placeholder",
                ],
                check=True,
                cwd=SKILL_DIR,
            )
            keep_records = [json.loads(line) for line in keep_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(keep_records), 1)
            self.assertEqual(keep_records[0]["llm_decision"], "keep")

    def test_rule_feedback_report_contains_sections(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-feedback-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "reviewed.jsonl"
            output_path = tmpdir_path / "report.md"
            records = [
                {
                    "title_en": "Example title",
                    "source_id": "nature",
                    "category": "other",
                    "rule_decision": "keep",
                    "llm_decision": "review",
                    "final_decision": "review",
                    "llm_reason": "ambiguous",
                }
            ]
            input_path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "rule_feedback_report.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                cwd=SKILL_DIR,
            )
            report = output_path.read_text(encoding="utf-8")
            self.assertIn("Rule Feedback Report", report)
            self.assertIn("Rule Keep But LLM Review", report)


if __name__ == "__main__":
    unittest.main()
