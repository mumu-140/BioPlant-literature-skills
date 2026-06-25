#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from tests.helpers import load_script_module
except ModuleNotFoundError:
    from helpers import load_script_module
from bio_literature_digest.fetching import http as fetch_http


def load_module():
    return load_script_module("fetch_feeds.py")


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

    def test_main_retries_failed_locator_with_proxy_and_merges_records(self) -> None:
        module = load_module()
        rss_text = """
        <rss><channel>
          <item>
            <title>A plant immune signaling circuit</title>
            <link>https://example.org/paper</link>
            <description>Plant immunity.</description>
          </item>
        </channel></rss>
        """
        with tempfile.TemporaryDirectory(prefix="bio-fetch-proxy-") as tmpdir:
            root = Path(tmpdir)
            watchlist = root / "watchlist.yaml"
            output = root / "raw.jsonl"
            watchlist.write_text(
                "\n".join(
                    [
                        "defaults:",
                        "  lookback_hours: 24",
                        "journals:",
                        "  - id: test-journal",
                        "    enabled: true",
                        "    journal_name: Test Journal",
                        "    source_locator: https://example.org/rss",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            argv = [
                "fetch_feeds.py",
                "--watchlist",
                str(watchlist),
                "--output",
                str(output),
                "--retry-failed-with-proxy",
            ]
            with mock.patch.object(fetch_http, "fetch_url", side_effect=RuntimeError("HTTP Error 403")):
                with mock.patch.object(fetch_http, "fetch_url_via_proxy", return_value=rss_text) as proxy_fetch:
                    with mock.patch.object(sys, "argv", argv):
                        exit_code = module.main()

            self.assertEqual(exit_code, 0)
            proxy_fetch.assert_called_once()
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["fetch_route"], "proxy")
            self.assertEqual(records[0]["journal"], "Test Journal")


if __name__ == "__main__":
    unittest.main()
