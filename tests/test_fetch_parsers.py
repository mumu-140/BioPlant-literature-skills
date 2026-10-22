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
    def test_public_url_validation_rejects_private_dns_results(self) -> None:
        private_result = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with mock.patch.object(fetch_http.socket, "getaddrinfo", return_value=private_result):
            with self.assertRaisesRegex(ValueError, "private or local"):
                fetch_http.validate_public_http_url("https://feed.example.org/rss")

    def test_public_url_validation_accepts_public_syntax_without_dns(self) -> None:
        fetch_http.validate_public_http_url("https://feed.example.org/rss", resolve_host=False)

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
        self.assertEqual(records[0]["doi"], "10.1093/plcell/koaf001/8123456")

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
        self.assertEqual(records[0]["doi"], "10.1073/pnas.2601234123")

    def test_parse_rss_extracts_doi_from_article_link_when_identifier_is_missing(self) -> None:
        module = load_module()
        rss_text = """
        <rss><channel>
          <item>
            <title>A plant immune signaling circuit</title>
            <link>https://doi.org/10.1126/sciadv.0000001</link>
            <pubDate>Sat, 14 Mar 2026 00:00:00 GMT</pubDate>
          </item>
        </channel></rss>
        """
        records = module.parse_feed_xml(
            rss_text,
            {"id": "science-advances", "journal_name": "Science Advances"},
            "https://example.org/rss",
        )
        self.assertEqual(records[0]["doi"], "10.1126/sciadv.0000001")

    def test_parse_pnas_rdf_extracts_channel_topic_tag_and_cleans_description(self) -> None:
        module = load_module()
        rdf_text = """<?xml version="1.0" encoding="UTF-8"?>
        <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                 xmlns="http://purl.org/rss/1.0/"
                 xmlns:dc="http://purl.org/dc/elements/1.1/">
          <channel>
            <title>Proceedings of the National Academy of Sciences: Plant Biology</title>
          </channel>
          <item>
            <title>A transposon inserted into HELD1 repressed maize husk leaf blade extension</title>
            <link>https://www.pnas.org/doi/abs/10.1073/pnas.2602491123?af=R</link>
            <description>Proceedings of the National Academy of Sciences, Volume 123, Issue 42, October 2026. &lt;br/&gt;SignificanceMaize husk leaves play an essential role.</description>
            <dc:identifier>doi:10.1073/pnas.2602491123</dc:identifier>
            <dc:date>2026-10-16T07:00:00Z</dc:date>
          </item>
        </rdf:RDF>
        """
        records = module.parse_feed_xml(
            rdf_text,
            {"id": "pnas", "journal_name": "PNAS", "publisher_family": "pnas"},
            "https://www.pnas.org/action/showFeed?type=searchTopic&taxonomyCode=topic&tagCode=plant-bio",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["tags"], ["Plant Biology"])
        self.assertEqual(records[0]["abstract"], "SignificanceMaize husk leaves play an essential role.")

    def test_parse_crossref_works_json_and_dedupe_merges_tags_and_abstract(self) -> None:
        module = load_module()
        crossref_json = json.dumps(
            {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1073/pnas.2602491123",
                            "title": ["A transposon inserted into <i>HELD1</i> repressed maize husk leaf blade extension"],
                            "published-online": {"date-parts": [[2026, 10, 16]]},
                            "abstract": "<jats:p>Full untruncated abstract about maize husk leaf blade extension and genetics.</jats:p>",
                            "author": [{"given": "San", "family": "Zhang"}],
                            "type": "journal-article",
                        }
                    ]
                }
            }
        )
        source_meta = {"id": "pnas", "journal_name": "PNAS", "publisher_family": "pnas", "group": "flagship-general"}
        cr_records = module.parse_source_payload(
            crossref_json,
            source_meta,
            "https://api.crossref.org/works?filter=issn:1091-6490",
        )
        self.assertEqual(len(cr_records), 1)
        self.assertEqual(cr_records[0]["published"], "2026-10-16T07:00:00Z")
        self.assertEqual(cr_records[0]["authors"], ["San Zhang"])
        self.assertNotIn("<jats:p>", cr_records[0]["abstract"])

        rss_record = dict(cr_records[0], abstract="Short...", tags=["Biological Sciences", "Plant Biology"], authors=["San Zhanghttps://ror.org/001"])
        merged = module.dedupe_journal_records([rss_record, cr_records[0]])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["tags"], ["Biological Sciences", "Plant Biology"])
        self.assertEqual(merged[0]["authors"], ["San Zhang"])
        self.assertIn("Full untruncated abstract", merged[0]["abstract"])

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
