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


class VisualDigestFilterTest(unittest.TestCase):
    def test_html_hides_broad_journal_human_disease_but_csv_keeps_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-visual-filter-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "localized.jsonl"
            html_path = tmpdir_path / "digest.html"
            csv_path = tmpdir_path / "digest.csv"
            xlsx_path = tmpdir_path / "digest.xlsx"
            records = [
                {
                    "source_id": "nature-communications",
                    "journal": "Nature Communications",
                    "group": "nature-family",
                    "publication_stage": "journal",
                    "category": "other",
                    "title_en": "Targeted cancer imaging in human patients",
                    "title_zh": "人类患者中的靶向癌症成像",
                    "summary_zh": "这段总结不应出现在界面。",
                    "abstract": "Cancer imaging in human patients.",
                    "doi": "10.1000/human",
                    "article_url": "https://example.org/human",
                    "publish_date": "2026-03-14T01:00:00Z",
                    "authors": ["A One", "B Two", "C Three", "D Four", "E Five", "F Six"],
                },
                {
                    "source_id": "nature-communications",
                    "journal": "Nature Communications",
                    "group": "nature-family",
                    "publication_stage": "journal",
                    "category": "plant-biology",
                    "title_en": "Auxin control of root growth in rice",
                    "title_zh": "生长素调控水稻根生长",
                    "summary_zh": "这段总结不应出现在界面。",
                    "abstract": "Plant root biology study in rice.",
                    "doi": "10.1000/plant",
                    "article_url": "https://example.org/plant",
                    "publish_date": "2026-03-14T02:00:00Z",
                    "authors": ["A One", "B Two", "C Three", "D Four", "E Five", "F Six"],
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

            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("Auxin control of root growth in rice", html_text)
            self.assertNotIn("Targeted cancer imaging in human patients", html_text)
            self.assertIn("Authors: A One, B Two, D Four, E Five, F Six", html_text)
            self.assertNotIn("这段总结不应出现在界面", html_text)

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["title_en"], "Auxin control of root growth in rice")
            self.assertEqual(rows[1]["title_en"], "Targeted cancer imaging in human patients")


if __name__ == "__main__":
    unittest.main()
