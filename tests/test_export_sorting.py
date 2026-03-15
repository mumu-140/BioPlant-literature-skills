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


class ExportSortingTest(unittest.TestCase):
    def test_review_records_sort_after_keep_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-export-sort-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "localized.jsonl"
            html_path = tmpdir_path / "digest.html"
            csv_path = tmpdir_path / "digest.csv"
            xlsx_path = tmpdir_path / "digest.xlsx"
            records = [
                {
                    "source_id": "nature-genetics",
                    "journal": "Nature Genetics",
                    "publication_stage": "journal",
                    "category": "omics",
                    "title_en": "Certain paper",
                    "title_zh": "明确论文",
                    "summary_zh": "明确论文摘要。",
                    "abstract": "Clear biology abstract.",
                    "doi": "10.1000/certain",
                    "article_url": "https://example.org/certain",
                    "publish_date": "2026-03-14T01:00:00Z",
                    "final_decision": "keep",
                    "llm_confidence": 0.95,
                },
                {
                    "source_id": "nature-genetics",
                    "journal": "Nature Genetics",
                    "publication_stage": "journal",
                    "category": "omics",
                    "title_en": "Uncertain paper",
                    "title_zh": "不确定论文",
                    "summary_zh": "不确定论文摘要。",
                    "abstract": "Ambiguous biology abstract.",
                    "doi": "10.1000/uncertain",
                    "article_url": "https://example.org/uncertain",
                    "publish_date": "2026-03-14T02:00:00Z",
                    "final_decision": "review",
                    "llm_confidence": 0.62,
                },
            ]
            input_path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "export_digest.py"),
                    "--input",
                    str(input_path),
                    "--rules",
                    str(SKILL_DIR / "references" / "category_rules.yaml"),
                    "--html-output",
                    str(html_path),
                    "--csv-output",
                    str(csv_path),
                    "--xlsx-output",
                    str(xlsx_path),
                    "--template",
                    str(SKILL_DIR / "assets" / "email_template.html"),
                ],
                check=True,
                cwd=SKILL_DIR,
            )

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["title_en"] for row in rows], ["Certain paper", "Uncertain paper"])


if __name__ == "__main__":
    unittest.main()
