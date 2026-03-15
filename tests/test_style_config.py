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


class StyleConfigTest(unittest.TestCase):
    def test_style_override_css_is_injected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-style-config-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "localized.jsonl"
            style_path = tmpdir_path / "style.yaml"
            html_path = tmpdir_path / "digest.html"
            csv_path = tmpdir_path / "digest.csv"
            xlsx_path = tmpdir_path / "digest.xlsx"
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
                    "--style-config",
                    str(style_path),
                ],
                check=True,
                cwd=SKILL_DIR,
            )
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("font-size: 30px;", html_text)


if __name__ == "__main__":
    unittest.main()
