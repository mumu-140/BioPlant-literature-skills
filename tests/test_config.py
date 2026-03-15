#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


SKILL_DIR = Path(__file__).resolve().parents[1]
REFERENCES_DIR = SKILL_DIR / "references"


class ConfigTest(unittest.TestCase):
    def test_watchlist_has_unique_ids_and_names(self) -> None:
        data = yaml.safe_load((REFERENCES_DIR / "journal_watchlist.yaml").read_text(encoding="utf-8"))
        journals = data["journals"]
        ids = [journal["id"] for journal in journals]
        names = [journal["journal_name"] for journal in journals]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))
        for journal in journals:
            self.assertIn(journal["source_strategy"], {"official_feed_or_toc", "official_feed", "official_toc", "api"})
            self.assertIn("enabled", journal)
            self.assertIn("topic_bias", journal)

    def test_category_rules_have_other_fallback_and_required_columns(self) -> None:
        data = yaml.safe_load((REFERENCES_DIR / "category_rules.yaml").read_text(encoding="utf-8"))
        categories = data["categories"]
        category_ids = [category["id"] for category in categories]
        self.assertIn("other", category_ids)
        self.assertEqual(data["classification_policy"]["fallback_category"], "other")

        required_columns = data["output_schema"]["required_columns"]
        self.assertIn("publication_stage", required_columns)
        self.assertIn("title_en", required_columns)
        self.assertIn("title_zh", required_columns)
        self.assertIn("authors", required_columns)
        self.assertIn("summary_zh", required_columns)
        self.assertIn("doi", required_columns)
        display_priority = data["display_priority"]
        self.assertEqual(display_priority["default_grouping_mode"], "journal")
        self.assertIn("journal", display_priority["available_grouping_modes"])
        self.assertIn("priority", display_priority["available_grouping_modes"])


if __name__ == "__main__":
    unittest.main()
