#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from tests.helpers import load_script_module, SKILL_DIR, SCRIPTS_DIR
except ModuleNotFoundError:
    from helpers import load_script_module, SKILL_DIR, SCRIPTS_DIR


def load_module():
    return load_script_module("llm_review.py")


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
                    str(SCRIPTS_DIR / "optimization_reports.py"),
                    "rule-feedback",
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

    def test_nvidia_review_only_sends_uncertain_records(self) -> None:
        module = load_module()
        records = [
            {
                "title_en": "A clear plant single-cell atlas",
                "category": "plant-biology",
                "publication_stage": "journal",
                "relevance_status": "keep",
                "relevance_reason": "matched keep keywords: plant",
                "relevance_review_needed": False,
                "abstract": "A plant study.",
            },
            {
                "title_en": "An ambiguous field observation",
                "category": "other",
                "publication_stage": "journal",
                "relevance_status": "keep",
                "relevance_reason": "kept by default source scope",
                "relevance_review_needed": True,
                "abstract": "Ambiguous scope.",
            },
        ]
        ai_payload = [{"decision": "reject", "confidence": 0.81, "reason": "outside scope"}]

        with mock.patch.object(module, "review_records_with_nvidia", return_value=ai_payload) as mocked_review:
            payloads = module.nvidia_review_payloads(records, {"runtime": {"continue_on_error": True}})

        sent_records = mocked_review.call_args.args[0]
        self.assertEqual(len(sent_records), 1)
        self.assertEqual(sent_records[0]["title_en"], "An ambiguous field observation")
        self.assertEqual(payloads[0]["decision"], "keep")
        self.assertEqual(payloads[1]["decision"], "reject")

    def test_nvidia_review_falls_back_to_placeholder_when_unavailable(self) -> None:
        module = load_module()
        records = [
            {
                "title_en": "An ambiguous field observation",
                "category": "other",
                "publication_stage": "journal",
                "relevance_status": "keep",
                "relevance_reason": "kept by default source scope",
                "relevance_review_needed": True,
                "abstract": "Ambiguous scope.",
            }
        ]

        with mock.patch.object(module, "review_records_with_nvidia", side_effect=RuntimeError("quota exhausted")):
            payloads = module.nvidia_review_payloads(records, {"runtime": {"continue_on_error": True}})

        self.assertEqual(payloads[0]["decision"], "review")
        self.assertIn("ambiguous", payloads[0]["reason"].lower())


if __name__ == "__main__":
    unittest.main()
