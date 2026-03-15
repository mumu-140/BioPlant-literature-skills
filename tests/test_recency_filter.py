#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "normalize_and_dedupe.py"


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RecencyFilterTest(unittest.TestCase):
    def test_normalize_and_dedupe_keeps_only_recent_published_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-digest-recency-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "raw.jsonl"
            output_path = tmpdir_path / "normalized.jsonl"
            duplicates_path = tmpdir_path / "duplicates.jsonl"
            now = datetime.now(timezone.utc)
            rows = [
                {
                    "source_id": "nature-methods",
                    "journal": "Nature Methods",
                    "title": "Recent biology paper",
                    "link": "https://example.org/recent",
                    "published": iso_utc(now - timedelta(hours=2)),
                    "abstract": "A recent biology paper.",
                },
                {
                    "source_id": "nature-methods",
                    "journal": "Nature Methods",
                    "title": "Old biology paper",
                    "link": "https://example.org/old",
                    "published": iso_utc(now - timedelta(days=3)),
                    "abstract": "An old biology paper.",
                },
                {
                    "source_id": "nature-methods",
                    "journal": "Nature Methods",
                    "title": "Missing date paper",
                    "link": "https://example.org/missing-date",
                    "abstract": "This paper does not have a published date.",
                },
            ]
            with input_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row))
                    handle.write("\n")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--duplicates-output",
                    str(duplicates_path),
                    "--lookback-hours",
                    "24",
                ],
                check=True,
                cwd=SKILL_DIR,
            )

            normalized_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(normalized_rows), 1)
            self.assertEqual(normalized_rows[0]["title_en"], "Recent biology paper")

    def test_normalize_and_dedupe_supports_explicit_window(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-digest-window-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "raw.jsonl"
            output_path = tmpdir_path / "normalized.jsonl"
            rows = [
                {
                    "source_id": "nature-methods",
                    "journal": "Nature Methods",
                    "title": "Inside window",
                    "link": "https://example.org/inside",
                    "published": "2026-03-13T16:00:00Z",
                    "abstract": "Included in schedule window.",
                },
                {
                    "source_id": "nature-methods",
                    "journal": "Nature Methods",
                    "title": "Outside window",
                    "link": "https://example.org/outside",
                    "published": "2026-03-12T15:59:59Z",
                    "abstract": "Excluded from schedule window.",
                },
            ]
            with input_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row))
                    handle.write("\n")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--window-start",
                    "2026-03-12T16:00:00Z",
                    "--window-end",
                    "2026-03-14T00:00:00Z",
                ],
                check=True,
                cwd=SKILL_DIR,
            )

            normalized_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(normalized_rows), 1)
            self.assertEqual(normalized_rows[0]["title_en"], "Inside window")

    def test_normalize_and_dedupe_merges_url_and_doi_variants(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-digest-dedupe-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "raw.jsonl"
            output_path = tmpdir_path / "normalized.jsonl"
            now = datetime.now(timezone.utc)
            rows = [
                {
                    "source_id": "nature-communications",
                    "journal": "Nature Communications",
                    "title": "Joint control of precipitation and CO2 on global long-term patterns of plant nitrogen availability",
                    "link": "https://www.nature.com/articles/s41467-026-70358-7",
                    "published": iso_utc(now - timedelta(hours=1)),
                    "abstract": "",
                    "doi": "",
                },
                {
                    "source_id": "nature-communications",
                    "journal": "Nature Communications",
                    "title": "Joint control of precipitation and CO<sub>2</sub> on global long-term patterns of plant nitrogen availability",
                    "link": "https://www.nature.com/articles/s41467-026-70358-7",
                    "published": iso_utc(now - timedelta(hours=1)),
                    "abstract": "Detailed abstract.",
                    "doi": "10.1038/s41467-026-70358-7",
                },
            ]
            with input_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row))
                    handle.write("\n")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--lookback-hours",
                    "24",
                ],
                check=True,
                cwd=SKILL_DIR,
            )

            normalized_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(normalized_rows), 1)
            self.assertEqual(normalized_rows[0]["doi"], "10.1038/s41467-026-70358-7")
