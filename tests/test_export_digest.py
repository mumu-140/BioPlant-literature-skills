#!/usr/bin/env python3
"""Unified tests for scripts/export_digest.py.

Merged from:
  - test_export_sorting.py (CSV row order + interest stars)
  - test_style_config.py (CSS injection via --style-config)
  - test_visual_digest_filter.py (HTML hides filtered records, CSV keeps them)
"""
from __future__ import annotations

import csv
import json
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


class ExportDigestTest(unittest.TestCase):
    """All export_digest.py tests in one class with shared subprocess helper."""

    def _run_export(self, input_path: Path, tmpdir_path: Path, extra_args: list[str] | None = None) -> tuple[Path, Path, Path]:
        html_path = tmpdir_path / "digest.html"
        csv_path = tmpdir_path / "digest.csv"
        xlsx_path = tmpdir_path / "digest.xlsx"
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "export_digest.py"),
            "--input", str(input_path),
            "--rules", str(CANONICAL_PATHS["rules"]),
            "--html-output", str(html_path),
            "--csv-output", str(csv_path),
            "--xlsx-output", str(xlsx_path),
            "--template", str(SKILL_DIR / "assets" / "email_template.html"),
        ]
        if extra_args:
            cmd.extend(extra_args)
        subprocess.run(cmd, check=True, cwd=SKILL_DIR)
        return html_path, csv_path, xlsx_path

    def test_review_records_sort_after_keep_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-export-sort-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "localized.jsonl"
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
                    "interest_level": "非常感兴趣",
                    "interest_tag": "组学",
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
                    "interest_level": "一般",
                    "interest_tag": "组学",
                },
            ]
            write_jsonl(input_path, records)
            html_path, csv_path, _ = self._run_export(input_path, tmpdir_path)

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["title_en"] for row in rows], ["Certain paper", "Uncertain paper"])
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("★★★★★", html_text)
            self.assertIn("组学", html_text)

    def test_style_override_css_is_injected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-style-config-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "localized.jsonl"
            style_path = tmpdir_path / "style.yaml"
            input_path.write_text(
                json.dumps(
                    {
                        "source_id": "nature-methods",
                        "journal": "Nature Methods",
                        "publication_stage": "journal",
                        "category": "methods-datasets-resources",
                        "title_en": "Example title",
                        "title_zh": "示例标题",
                        "authors": ["A", "B", "C", "D", "E", "F"],
                        "abstract": "Example abstract.",
                        "doi": "10.1000/example",
                        "article_url": "https://example.org",
                        "publish_date": "2026-03-14T00:00:00Z",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            style_path.write_text("base_css: |\n  .hero h1 {\n    font-size: 30px;\n  }\n", encoding="utf-8")
            html_path, _, _ = self._run_export(input_path, tmpdir_path, ["--style-config", str(style_path)])
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("font-size: 30px;", html_text)

    def test_html_hides_broad_journal_human_disease_but_csv_keeps_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-visual-filter-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "localized.jsonl"
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
            write_jsonl(input_path, records)
            html_path, csv_path, _ = self._run_export(input_path, tmpdir_path)

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
