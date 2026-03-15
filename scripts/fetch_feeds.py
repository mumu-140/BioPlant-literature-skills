#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from common import current_timestamp_utc, isoformat_utc, load_watchlist, parse_datetime_guess, within_utc_window, write_jsonl


NON_ARTICLE_TITLE_EXACT = {
    "advisory board and contents",
    "subscription and copyright information",
}


def should_skip_record(record: dict[str, Any]) -> bool:
    title = str(record.get("title") or "").strip().lower()
    if title in NON_ARTICLE_TITLE_EXACT:
        return True
    return False


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(node: ET.Element, *names: str) -> str:
    for child in list(node):
        if local_name(child.tag) in names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def child_texts(node: ET.Element, *names: str) -> list[str]:
    values: list[str] = []
    for child in list(node):
        if local_name(child.tag) in names:
            text = "".join(child.itertext()).strip()
            if text:
                values.append(text)
    return values


def child_attr(node: ET.Element, child_name: str, attr_name: str) -> str:
    for child in list(node):
        if local_name(child.tag) == child_name and child.attrib.get(attr_name):
            return child.attrib[attr_name].strip()
    return ""


def parse_feed_xml(xml_text: str, source_meta: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    root_name = local_name(root.tag)
    records: list[dict[str, Any]] = []
    if root_name == "RDF":
        for item in root:
            if local_name(item.tag) != "item":
                continue
            categories = child_texts(item, "subject", "category")
            links = child_texts(item, "link", "url")
            abstract = child_text(item, "encoded", "description", "summary")
            records.append(
                {
                    "source_id": source_meta["id"],
                    "journal": source_meta["journal_name"],
                    "publisher_family": source_meta.get("publisher_family", ""),
                    "group": source_meta.get("group", ""),
                    "publication_stage": source_meta.get("publication_stage", "journal"),
                    "source_url": source_url,
                    "title": child_text(item, "title"),
                    "link": links[0] if links else "",
                    "published": child_text(item, "date", "published"),
                    "abstract": abstract,
                    "article_type": child_text(item, "type"),
                    "doi": child_text(item, "doi", "identifier"),
                    "tags": categories,
                    "authors": child_texts(item, "creator"),
                }
            )
        return records
    if root_name == "rss":
        channel = next((node for node in list(root) if local_name(node.tag) == "channel"), None)
        if channel is None:
            return records
        for item in channel:
            if local_name(item.tag) != "item":
                continue
            categories = [text for child in item if local_name(child.tag) == "category" for text in ["".join(child.itertext()).strip()] if text]
            records.append(
                {
                    "source_id": source_meta["id"],
                    "journal": source_meta["journal_name"],
                    "publisher_family": source_meta.get("publisher_family", ""),
                    "group": source_meta.get("group", ""),
                    "publication_stage": source_meta.get("publication_stage", "journal"),
                    "source_url": source_url,
                    "title": child_text(item, "title"),
                    "link": child_text(item, "link"),
                    "published": child_text(item, "pubDate", "published", "date"),
                    "abstract": child_text(item, "description", "encoded", "summary"),
                    "article_type": child_text(item, "type"),
                    "doi": child_text(item, "identifier"),
                    "tags": categories,
                }
            )
    elif root_name == "feed":
        for entry in root:
            if local_name(entry.tag) != "entry":
                continue
            categories = [child.attrib.get("term", "").strip() for child in entry if local_name(child.tag) == "category" and child.attrib.get("term")]
            link = child_attr(entry, "link", "href") or child_text(entry, "link")
            doi = child_text(entry, "doi", "identifier")
            if not doi:
                entry_id = child_text(entry, "id")
                if "doi.org/" in entry_id.lower():
                    doi = entry_id.rsplit("/", 1)[-1]
            records.append(
                {
                    "source_id": source_meta["id"],
                    "journal": source_meta["journal_name"],
                    "publisher_family": source_meta.get("publisher_family", ""),
                    "group": source_meta.get("group", ""),
                    "publication_stage": source_meta.get("publication_stage", "journal"),
                    "source_url": source_url,
                    "title": child_text(entry, "title"),
                    "link": link,
                    "published": child_text(entry, "published", "updated", "date"),
                    "abstract": child_text(entry, "summary", "content", "subtitle"),
                    "article_type": child_text(entry, "type"),
                    "doi": doi,
                    "tags": categories,
                }
            )
    return records


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        self._current_href = attr_map.get("href")
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        text = " ".join(part.strip() for part in self._buffer if part.strip()).strip()
        self.links.append((self._current_href, text))
        self._current_href = None
        self._buffer = []


def parse_oup_advance_html(html_text: str, source_meta: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    collector = LinkCollector()
    collector.feed(html_text)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for href, text in collector.links:
        if "/advance-article/" not in href:
            continue
        if len(text) < 20:
            continue
        link = urljoin(source_url, href)
        if link in seen:
            continue
        seen.add(link)
        records.append(
            {
                "source_id": source_meta["id"],
                "journal": source_meta["journal_name"],
                "publisher_family": source_meta.get("publisher_family", ""),
                "group": source_meta.get("group", ""),
                "publication_stage": source_meta.get("publication_stage", "journal"),
                "source_url": source_url,
                "title": text,
                "link": link,
                "published": "",
                "abstract": "",
                "article_type": "",
                "doi": "",
                "tags": [],
            }
        )
    return records


def parse_pnas_toc_html(html_text: str, source_meta: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    collector = LinkCollector()
    collector.feed(html_text)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for href, text in collector.links:
        if "/doi/" not in href:
            continue
        if len(text) < 20 or text.lower() in {"abstract", "full text", "pdf"}:
            continue
        link = urljoin(source_url, href)
        if link in seen:
            continue
        seen.add(link)
        records.append(
            {
                "source_id": source_meta["id"],
                "journal": source_meta["journal_name"],
                "publisher_family": source_meta.get("publisher_family", ""),
                "group": source_meta.get("group", ""),
                "publication_stage": source_meta.get("publication_stage", "journal"),
                "source_url": source_url,
                "title": text,
                "link": link,
                "published": "",
                "abstract": "",
                "article_type": "",
                "doi": "",
                "tags": [],
            }
        )
    return records


def fetch_url(url: str, user_agent: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_source_payload(payload: str, source_meta: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    strategy = source_meta.get("source_strategy", "official_feed_or_toc")
    if strategy == "official_toc":
        if "academic.oup.com" in source_url and "advance-articles" in source_url:
            return parse_oup_advance_html(payload, source_meta, source_url)
        if "pnas.org/toc/" in source_url:
            return parse_pnas_toc_html(payload, source_meta, source_url)
        return []
    try:
        return parse_feed_xml(payload, source_meta, source_url)
    except ET.ParseError:
        if "academic.oup.com" in source_url and "advance-articles" in source_url:
            return parse_oup_advance_html(payload, source_meta, source_url)
        if "pnas.org/toc/" in source_url:
            return parse_pnas_toc_html(payload, source_meta, source_url)
        raise


def select_journals(watchlist: dict[str, Any], journal_ids: list[str]) -> list[dict[str, Any]]:
    journals = [journal for journal in watchlist.get("journals", []) if journal.get("enabled")]
    if not journal_ids:
        return journals
    selected = []
    allowed = set(journal_ids)
    for journal in journals:
        if journal["id"] in allowed:
            selected.append(journal)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch RSS/Atom records for configured journals.")
    parser.add_argument("--watchlist", required=True, help="Path to journal_watchlist.yaml")
    parser.add_argument("--output", required=True, help="Output JSONL file")
    parser.add_argument("--journal", action="append", default=[], help="Restrict to one or more journal ids")
    parser.add_argument("--lookback-hours", type=int, default=None, help="Override lookback window")
    parser.add_argument("--window-start", help="Inclusive UTC window start in ISO-8601 format")
    parser.add_argument("--window-end", help="Inclusive UTC window end in ISO-8601 format")
    parser.add_argument("--limit-per-journal", type=int, default=50, help="Maximum records to emit per journal")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    parser.add_argument(
        "--user-agent",
        default="bio-literature-digest/0.1 (+https://local.codex)",
        help="HTTP User-Agent header",
    )
    args = parser.parse_args()

    watchlist = load_watchlist(args.watchlist)
    defaults = watchlist.get("defaults", {})
    lookback_hours = args.lookback_hours if args.lookback_hours is not None else int(defaults.get("lookback_hours", 24))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    window_start = parse_datetime_guess(args.window_start) if args.window_start else None
    window_end = parse_datetime_guess(args.window_end) if args.window_end else None

    selected_journals = select_journals(watchlist, args.journal)
    output_records: list[dict[str, Any]] = []
    skipped_missing = 0

    for journal in selected_journals:
        locators = journal.get("source_locator")
        if not locators:
            skipped_missing += 1
            print(f"[skip] {journal['id']}: missing source_locator", file=sys.stderr)
            continue
        locator_list = locators if isinstance(locators, list) else [locators]
        journal_records: list[dict[str, Any]] = []
        for locator in locator_list:
            try:
                xml_text = fetch_url(locator, args.user_agent, args.timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"[error] {journal['id']}: {exc}", file=sys.stderr)
                continue
            try:
                parsed_records = parse_source_payload(xml_text, journal, locator)
            except ET.ParseError as exc:
                print(f"[error] {journal['id']}: XML parse failure: {exc}", file=sys.stderr)
                continue
            journal_records.extend(parsed_records)
        filtered_records = []
        for record in journal_records:
            if should_skip_record(record):
                continue
            published_dt = parse_datetime_guess(record.get("published"))
            if window_start is not None or window_end is not None:
                if published_dt is not None and not within_utc_window(published_dt, window_start, window_end):
                    continue
            elif published_dt is not None and published_dt < cutoff:
                continue
            record["fetched_at"] = current_timestamp_utc()
            record["published_at"] = isoformat_utc(published_dt)
            filtered_records.append(record)
        output_records.extend(filtered_records[: args.limit_per_journal])
        print(f"[ok] {journal['id']}: {len(filtered_records[: args.limit_per_journal])} records", file=sys.stderr)

    write_jsonl(Path(args.output), output_records)
    print(
        f"Wrote {len(output_records)} raw records to {args.output} "
        f"from {len(selected_journals) - skipped_missing} configured sources.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
