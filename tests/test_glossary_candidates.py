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
            input_path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_glossary_candidates.py"),
                    "--input",
                    str(input_path),
                    "--glossary",
                    str(SKILL_DIR / "references" / "bio_translation_glossary.yaml"),
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
