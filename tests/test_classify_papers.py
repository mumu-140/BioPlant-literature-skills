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
    return load_script_module("classify_papers.py")


class ClassifyPapersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.rules = yaml.safe_load(CANONICAL_PATHS["rules"].read_text(encoding="utf-8"))

    def test_horizontal_gene_transfer_uses_evolutionary_genomics(self) -> None:
        record = {
            "journal": "Nature Genetics",
            "title_en": "Horizontal gene transfer drives gene family diversification across land plants",
            "abstract": "Comparative genomics and phylogenetic analysis resolve recurrent transfers.",
            "tags": ["HGT", "Plant evolution"],
        }
        annotated = self.module.classify_record(record, self.rules)
        self.assertEqual("evolutionary-comparative-genomics", annotated["category"])
        self.assertGreater(annotated["category_score"], 0)

    def test_de_novo_protein_design_uses_biodesign_category(self) -> None:
        record = {
            "journal": "Nature Biotechnology",
            "title_en": "Generative de novo design of programmable protein binders",
            "abstract": "A diffusion model engineers synthetic proteins with validated binding activity.",
            "tags": ["Protein design", "Synthetic biology"],
        }
        annotated = self.module.classify_record(record, self.rules)
        self.assertEqual("synthetic-biology-biodesign", annotated["category"])

    def test_category_output_includes_ranked_evidence(self) -> None:
        record = {
            "journal": "Nucleic Acids Research",
            "title_en": "A searchable database and benchmark for plant transcription factor binding sites",
            "abstract": "The resource integrates genomic annotations and motif evidence.",
            "tags": ["Databases", "Plant molecular biology"],
        }
        annotated = self.module.classify_record(record, self.rules)
        self.assertEqual("methods-datasets-resources", annotated["category"])
        self.assertTrue(annotated["category_scores"])
        self.assertIn("score", annotated["category_scores"][0])


if __name__ == "__main__":
    unittest.main()
