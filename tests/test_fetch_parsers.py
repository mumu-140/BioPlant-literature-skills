#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "fetch_feeds.py"


def load_module():
    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("fetch_feeds_module", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load fetch_feeds.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FetchParserTest(unittest.TestCase):
    def test_should_skip_front_matter_titles(self) -> None:
        module = load_module()
        self.assertTrue(module.should_skip_record({"title": "Advisory Board and Contents"}))
        self.assertTrue(module.should_skip_record({"title": "Subscription and Copyright Information"}))
        self.assertFalse(module.should_skip_record({"title": "A single-cell atlas of maize roots"}))

    def test_parse_oup_advance_html_extracts_article_links(self) -> None:
        module = load_module()
        html_text = """
        <html><body>
        <a href="/plcell/advance-article/doi/10.1093/plcell/koaf001/8123456">A single-cell view of maize root patterning</a>
        <a href="/plcell/advance-article/doi/10.1093/plcell/koaf002/8123457">Short</a>
        </body></html>
        """
        records = module.parse_oup_advance_html(
            html_text,
            {"id": "the-plant-cell", "journal_name": "The Plant Cell", "publisher_family": "aspb", "group": "plant-core"},
            "https://academic.oup.com/plcell/advance-articles",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["journal"], "The Plant Cell")
        self.assertIn("/plcell/advance-article/doi/10.1093/plcell/koaf001/8123456", records[0]["link"])

    def test_parse_pnas_toc_html_extracts_doi_links(self) -> None:
        module = load_module()
        html_text = """
        <html><body>
        <a href="/doi/10.1073/pnas.2601234123">A plant immune signaling circuit with broad relevance</a>
        <a href="/doi/10.1073/pnas.2601234123">Abstract</a>
        </body></html>
        """
        records = module.parse_pnas_toc_html(
            html_text,
            {"id": "pnas", "journal_name": "PNAS", "publisher_family": "pnas", "group": "flagship-general"},
            "https://www.pnas.org/toc/pnas/current",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["journal"], "PNAS")
        self.assertIn("/doi/10.1073/pnas.2601234123", records[0]["link"])


if __name__ == "__main__":
    unittest.main()
