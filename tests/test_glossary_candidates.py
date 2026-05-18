#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from scripts.project_layout import canonical_paths

try:
    from tests.helpers import write_jsonl
except ImportError:
    from helpers import write_jsonl


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
CANONICAL_PATHS = canonical_paths()


class GlossaryCandidatesTest(unittest.TestCase):
    def test_builds_candidate_report_from_digest_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-glossary-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "localized.jsonl"
            yaml_output = tmpdir_path / "glossary_candidates.yaml"
            report_output = tmpdir_path / "glossary_candidates.md"
            records = [
                {
                    "title_en": "Rhizosphere microbiome dynamics in maize",
                    "abstract": "Rhizosphere microbiome dynamics define plant health in maize roots.",
                    "tags": ["plant"],
                }
            ]
            write_jsonl(input_path, records)
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "optimization_reports.py"),
                    "glossary-candidates",
                    "--input",
                    str(input_path),
                    "--glossary",
                    str(CANONICAL_PATHS["glossary"]),
                    "--yaml-output",
                    str(yaml_output),
                    "--report-output",
                    str(report_output),
                ],
                check=True,
                cwd=SKILL_DIR,
            )

            report_text = report_output.read_text(encoding="utf-8")
            self.assertIn("Glossary Candidate Report", report_text)
            self.assertTrue(yaml_output.exists())


if __name__ == "__main__":
    unittest.main()
