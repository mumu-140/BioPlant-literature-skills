#!/usr/bin/env python3
"""Unit tests for bio_literature_digest.identity — DOI/URL/title normalization.

Covers the canonical implementations directly (src/ package path) and the
``scripts/common.py`` re-export shim that all pipeline scripts import through.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
SRC_DIR = SKILL_DIR / "src"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bio_literature_digest.identity import (
    canonicalize_doi,
    canonicalize_url,
    extract_doi,
    normalize_title,
    normalize_whitespace,
)
import common


class CanonicalizeDoiTest(unittest.TestCase):
    def test_lowercases_and_strips(self) -> None:
        self.assertEqual(canonicalize_doi(" 10.1038/S41586-025-00001-X "), "10.1038/s41586-025-00001-x")

    def test_strips_resolver_prefix(self) -> None:
        self.assertEqual(canonicalize_doi("https://doi.org/10.1038/s41586.025.00001.x"), "10.1038/s41586.025.00001.x")
        self.assertEqual(canonicalize_doi("http://dx.doi.org/10.1234/abc"), "10.1234/abc")

    def test_strips_doi_scheme_prefix(self) -> None:
        self.assertEqual(canonicalize_doi("doi: 10.1234/abc"), "10.1234/abc")

    def test_empty_input(self) -> None:
        self.assertEqual(canonicalize_doi(None), "")
        self.assertEqual(canonicalize_doi(""), "")


class ExtractDoiTest(unittest.TestCase):
    def test_extracts_from_free_text(self) -> None:
        self.assertEqual(extract_doi("See https://doi.org/10.1234/journal.2026.001 for details."), "10.1234/journal.2026.001")

    def test_strips_trailing_punctuation(self) -> None:
        self.assertEqual(extract_doi("The DOI is 10.1234/abc-def."), "10.1234/abc-def")

    def test_no_doi_found(self) -> None:
        self.assertEqual(extract_doi("No identifier here."), "")
        self.assertEqual(extract_doi(None), "")


class CanonicalizeUrlTest(unittest.TestCase):
    def test_strips_tracking_params(self) -> None:
        url = "https://Example.com/path?utm_source=rss&id=42&fbclid=abc"
        self.assertEqual(canonicalize_url(url), "https://example.com/path?id=42")

    def test_drops_fragment_and_keeps_non_tracking_query(self) -> None:
        url = "HTTPS://example.com/page?utm_medium=x&id=1#section"
        self.assertEqual(canonicalize_url(url), "https://example.com/page?id=1")

    def test_non_url_input_returned_stripped(self) -> None:
        self.assertEqual(canonicalize_url("not-a-url"), "not-a-url")
        self.assertEqual(canonicalize_url(None), "")

    def test_empty_path_becomes_root(self) -> None:
        self.assertEqual(canonicalize_url("https://example.com?utm_source=rss"), "https://example.com/")


class NormalizeTitleTest(unittest.TestCase):
    def test_lowercases_and_collapses_non_alphanumerics(self) -> None:
        self.assertEqual(normalize_title("A CRISPR-Based Screen — Genome-wide!"), "a crispr based screen genome wide")

    def test_strips_html_entities_and_tags(self) -> None:
        self.assertEqual(normalize_title("<b>&amp;AMP;</b> pathways"), "amp pathways")

    def test_empty_input(self) -> None:
        self.assertEqual(normalize_whitespace(None), "")


class CommonShimCompatibilityTest(unittest.TestCase):
    """``scripts/common.py`` must keep re-exporting the moved helpers."""

    def test_identity_names_are_reexported(self) -> None:
        self.assertIs(common.canonicalize_doi, canonicalize_doi)
        self.assertIs(common.canonicalize_url, canonicalize_url)
        self.assertIs(common.extract_doi, extract_doi)
        self.assertIs(common.normalize_title, normalize_title)
        self.assertIs(common.normalize_whitespace, normalize_whitespace)
        self.assertIs(common.DOI_PATTERN, __import__("bio_literature_digest.identity", fromlist=["DOI_PATTERN"]).DOI_PATTERN)


if __name__ == "__main__":
    unittest.main()
