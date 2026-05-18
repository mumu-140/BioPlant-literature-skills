#!/usr/bin/env python3
from __future__ import annotations

import unittest

import yaml
from scripts.project_layout import canonical_paths

try:
    from tests.helpers import load_script_module
except ModuleNotFoundError:
    from helpers import load_script_module

CANONICAL_PATHS = canonical_paths()


def load_module():
    return load_script_module("filter_bio_relevance.py")


class FilterRulesTest(unittest.TestCase):
    def test_nature_news_is_rejected_by_editorial_doi(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
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
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
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
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
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
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
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
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
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

    def test_briefing_with_bio_signal_uses_normal_relevance_rules(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature",
            "journal": "Nature",
            "group": "flagship-general",
            "title_en": "Briefing chat: Plant genome editing reshapes crop breeding",
            "abstract": "A short briefing about CRISPR-enabled plant breeding and crop genetics.",
            "doi": "10.1038/d41586-026-00000-0",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertTrue(keep, annotated["relevance_reason"])

    def test_manual_title_reject_fragment_is_rejected(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature",
            "journal": "Nature",
            "group": "flagship-general",
            "title_en": "Gaze stabilization: Bats do move their eyes but differently from mice",
            "abstract": "A short feature on bat eye movements.",
            "doi": "10.1038/d41586-026-00001-1",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("manual title reject", annotated["relevance_reason"])

    def test_manual_title_reject_fragment_handles_recent_current_biology_reject(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "current-biology",
            "journal": "Current Biology",
            "group": "flagship-general",
            "title_en": "Mechanical regulation of cuboidal-to-squamous epithelial transition in the Drosophila developing wing",
            "abstract": "A Drosophila wing morphogenesis study.",
            "doi": "10.1016/j.cub.2026.02.035",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("manual title reject", annotated["relevance_reason"])

    def test_correction_to_prefix_is_rejected(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature",
            "journal": "Nature",
            "group": "flagship-general",
            "title_en": "Correction to \u201cRice blast pathogen effector AvrPib compromises disease resistance by targeting Raf-like protein kinase OsMAPKKK72 to inhibit MAPK signaling\u201d",
            "abstract": "A correction notice rather than a research paper.",
            "doi": "10.1038/s41467-026-00000-0",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("editorial title prefix", annotated["relevance_reason"])

    def test_pure_human_cancer_mechanism_is_rejected(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "cell",
            "journal": "Cell",
            "group": "flagship-general",
            "title_en": "Human cancer signaling mechanisms drive tumor progression",
            "abstract": "Patient tumor cells reveal oncogenic pathway regulation in carcinoma progression.",
            "doi": "10.1016/j.cell.2026.02.018",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("pure human cancer or disease mechanism", annotated["relevance_reason"])

    def test_generalizable_human_or_mouse_method_is_kept(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature-methods",
            "journal": "Nature Methods",
            "group": "methods-core",
            "title_en": "A cross-species single-cell perturbation method for human and mouse models",
            "abstract": "The protocol benchmarks transferable gene regulatory inference for plant and animal datasets.",
            "doi": "10.1038/s41592-026-00000-0",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertTrue(keep, annotated["relevance_reason"])
        self.assertFalse(annotated["relevance_review_needed"])

    def test_default_scope_keep_is_marked_for_ai_review(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature-plants",
            "journal": "Nature Plants",
            "group": "plant-core",
            "title_en": "A perspective on future field observations",
            "abstract": "A broad field note without specific molecular or method signal.",
            "doi": "10.1038/s41477-026-00000-0",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertTrue(keep, annotated["relevance_reason"])
        self.assertTrue(annotated["relevance_review_needed"])
        self.assertEqual(annotated["relevance_certainty"], "review-needed")


    def test_biotech_news_roundup_is_rejected(self) -> None:
        module = load_module()
        rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))
        watchlist = yaml.safe_load(CANONICAL_PATHS["watchlist"].read_text(encoding="utf-8"))
        watchlist["by_id"] = {journal["id"]: journal for journal in watchlist["journals"]}
        record = {
            "source_id": "nature-biotechnology",
            "journal": "Nature Biotechnology",
            "group": "methods-core",
            "title_en": "Biotech news from around the world",
            "abstract": "A recurring global biotech news roundup rather than a primary research article.",
            "doi": "10.1038/s41587-026-03063-x",
            "tags": [],
        }
        keep, annotated = module.evaluate_record(record, rules, watchlist)
        self.assertFalse(keep)
        self.assertIn("editorial title prefix", annotated["relevance_reason"])


if __name__ == "__main__":
    unittest.main()
