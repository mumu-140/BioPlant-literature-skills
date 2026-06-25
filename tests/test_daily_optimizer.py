#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts import optimize_daily_results


class DailyOptimizerTest(unittest.TestCase):
    def test_apply_ai_plan_consumes_only_valid_conservative_updates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-optimize-") as tmpdir:
            root = Path(tmpdir)
            rules_path = root / "category_rules.yaml"
            glossary_path = root / "glossary.yaml"
            rules_path.write_text(
                yaml.safe_dump(
                    {
                        "relevance_filter": {"keep_keywords": [], "hard_reject_keywords": []},
                        "categories": [{"id": "plant-biology", "keywords": []}],
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            glossary_path.write_text("replacements: []\n", encoding="utf-8")
            rows = [
                {
                    "digest_date": "2026-06-25",
                    "doi": "10.1000/domain-peptide",
                    "title_en": "Domain-peptide interaction in plant immunity",
                    "abstract": "The work studies a domain-peptide interaction.",
                    "admission_tier": "apply",
                },
                {
                    "digest_date": "2026-06-25",
                    "doi": "10.1000/observe",
                    "title_en": "Weak observation term",
                    "abstract": "Weak observation term.",
                    "admission_tier": "observe",
                },
            ]
            plan = {
                "rule_updates": {
                    "keep_keywords": [{"keyword": "domain-peptide", "row_index": 1, "reason": "seen in title"}],
                    "hard_reject_keywords": [{"keyword": "weak observation", "row_index": 2, "reason": "observe only"}],
                },
                "glossary_updates": [
                    {"source": "domain-peptide", "target": "结构域-肽", "row_index": 1, "reason": "reviewer translation"}
                ],
            }
            args = argparse.Namespace(
                rules=rules_path,
                glossary=glossary_path,
                apply=True,
                max_candidate_rows=30,
                max_selected_rows=8,
            )

            applied = optimize_daily_results.apply_ai_plan(plan, rows, args)

            rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
            glossary = yaml.safe_load(glossary_path.read_text(encoding="utf-8"))
            self.assertIn("domain-peptide", rules["relevance_filter"]["keep_keywords"])
            self.assertNotIn("weak observation", rules["relevance_filter"]["hard_reject_keywords"])
            self.assertEqual(glossary["replacements"][0]["target"], "结构域-肽")
            self.assertEqual(len(applied["selected_rows"]), 1)
            self.assertEqual(applied["selected_rows"][0]["key_kind"], "doi")


if __name__ == "__main__":
    unittest.main()
