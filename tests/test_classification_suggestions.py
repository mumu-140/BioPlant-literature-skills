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


class ClassificationSuggestionsTest(unittest.TestCase):
    def test_builds_classification_suggestions_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-classify-suggest-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            classified_path = tmpdir_path / "classified.jsonl"
            reviewed_path = tmpdir_path / "reviewed.jsonl"
            md_path = tmpdir_path / "classification_suggestions.md"
            json_path = tmpdir_path / "classification_suggestions.json"
            classified_path.write_text(
                json.dumps(
                    {
                        "source_id": "nature-communications",
                        "category": "other",
                        "title_en": "Rhizosphere microbiome dynamics in maize",
                        "abstract": "Rhizosphere microbiome dynamics define plant health in maize roots.",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            reviewed_path.write_text(
                json.dumps(
                    {
                        "source_id": "nature-communications",
                        "final_decision": "review",
                        "llm_reason": "ambiguous",
                        "title_en": "Rhizosphere microbiome dynamics in maize",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "classification_suggestions.py"),
                    "--classified",
                    str(classified_path),
                    "--reviewed",
                    str(reviewed_path),
                    "--markdown-output",
                    str(md_path),
                    "--json-output",
                    str(json_path),
                ],
                check=True,
                cwd=SKILL_DIR,
            )
            self.assertIn("Classification Suggestions Report", md_path.read_text(encoding="utf-8"))
            self.assertTrue(json_path.exists())


if __name__ == "__main__":
    unittest.main()
