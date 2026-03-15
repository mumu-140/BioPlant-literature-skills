#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "filter_bio_relevance.py"


def load_module():
    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("filter_bio_relevance_module", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load filter_bio_relevance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FilterRulesTest(unittest.TestCase):
    def test_nature_news_is_rejected_by_editorial_doi(self) -> None:
        module = load_module()
        rules = yaml.safe_load((SKILL_DIR / "references" / "category_rules.yaml").read_text(encoding="utf-8"))
        watchlist = yaml.safe_load((SKILL_DIR / "references" / "journal_watchlist.yaml").read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature",
            "journal": "Nature",
            "group": "flagship-general",
            "title_en": "Top brass in China reaffirm goal to be world leaders in tech, AI",
            "abstract": "A policy and strategy news article.",
            "doi": "10.1038/d41586-026-00814-3",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("editorial DOI", annotated["relevance_reason"])

    def test_cell_biology_paper_is_not_rejected_by_strict_source_rule(self) -> None:
        module = load_module()
        rules = yaml.safe_load((SKILL_DIR / "references" / "category_rules.yaml").read_text(encoding="utf-8"))
        watchlist = yaml.safe_load((SKILL_DIR / "references" / "journal_watchlist.yaml").read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "cell",
            "journal": "Cell",
            "group": "flagship-general",
            "title_en": "Pluripotent stem-cell-based screening uncovers sildenafil as a mitochondrial disease therapy",
            "abstract": "Using patient-derived stem cell models, the study identifies a therapy for mitochondrial disease.",
            "doi": "10.1016/j.cell.2026.02.008",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertTrue(keep, annotated["relevance_reason"])

    def test_species_distribution_ecology_is_hard_rejected(self) -> None:
        module = load_module()
        rules = yaml.safe_load((SKILL_DIR / "references" / "category_rules.yaml").read_text(encoding="utf-8"))
        watchlist = yaml.safe_load((SKILL_DIR / "references" / "journal_watchlist.yaml").read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "pnas",
            "journal": "PNAS",
            "group": "flagship-general",
            "title_en": "Convolutional neural networks outperform other presence-only species distribution modeling algorithms",
            "abstract": "Species distribution models are evaluated across ecological datasets.",
            "doi": "10.1073/pnas.2514886123",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("hard reject", annotated["relevance_reason"])

    def test_nature_communications_requires_direct_bio_signal(self) -> None:
        module = load_module()
        rules = yaml.safe_load((SKILL_DIR / "references" / "category_rules.yaml").read_text(encoding="utf-8"))
        watchlist = yaml.safe_load((SKILL_DIR / "references" / "journal_watchlist.yaml").read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature-communications",
            "journal": "Nature Communications",
            "group": "nature-family",
            "title_en": "A hydro-topological strategy enables self-regulating biofilms for sustainable wastewater treatment",
            "abstract": "Engineered biofilms regulate microbial function in wastewater treatment reactors.",
            "doi": "10.1038/s41467-026-70682-y",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertTrue(keep, annotated["relevance_reason"])

    def test_nature_communications_rejects_ecology_without_bio_signal(self) -> None:
        module = load_module()
        rules = yaml.safe_load((SKILL_DIR / "references" / "category_rules.yaml").read_text(encoding="utf-8"))
        watchlist = yaml.safe_load((SKILL_DIR / "references" / "journal_watchlist.yaml").read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature-communications",
            "journal": "Nature Communications",
            "group": "nature-family",
            "title_en": "The evolutionary consequences of behavioural plasticity",
            "abstract": "A broad behavioral evolution theory article.",
            "doi": "10.1038/s41467-026-70632-8",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("hard reject", annotated["relevance_reason"])


if __name__ == "__main__":
    unittest.main()
