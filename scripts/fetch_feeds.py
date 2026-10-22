#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    from scripts._bootstrap import SRC_DIR as _SRC_DIR  # noqa: F401
except ModuleNotFoundError:
    from _bootstrap import SRC_DIR as _SRC_DIR  # noqa: F401
from bio_literature_digest.fetching.http import fetch_and_parse_locator

try:
    from scripts.common import current_timestamp_utc, extract_doi, isoformat_utc, load_watchlist, parse_datetime_guess, within_utc_window, write_jsonl
except ModuleNotFoundError:
    from common import current_timestamp_utc, extract_doi, isoformat_utc, load_watchlist, parse_datetime_guess, within_utc_window, write_jsonl


NON_ARTICLE_TITLE_EXACT = {
    "advisory board and contents",
    "subscription and copyright information",
    "in this issue",
}

PNAS_DESCRIPTION_PREFIX_RE = re.compile(
    r"^Proceedings of the National Academy of Sciences,\s*(?:Volume\s+\d+,\s*Issue\s+\d+,\s*[A-Za-z]+\s+\d{4}|ahead of print)\.\s*(?:<br\s*/?>)?\s*",
    re.IGNORECASE,
)


def clean_inline_markup(text: str) -> str:
    if not text:
        return ""
    unescaped = html.unescape(text)
    stripped = re.sub(r"<[^>]+>", " ", unescaped)
    return " ".join(stripped.split()).strip()


def clean_jats_abstract(raw_abstract: str) -> str:
    if not raw_abstract:
        return ""
    cleaned = re.sub(r"<jats:title[^>]*>\s*(?:Abstract|Significance)\s*</jats:title>", " ", raw_abstract, flags=re.IGNORECASE)
    cleaned = PNAS_DESCRIPTION_PREFIX_RE.sub("", cleaned)
    return clean_inline_markup(cleaned)


def extract_rdf_channel_tags(root: ET.Element, source_meta: dict[str, Any]) -> list[str]:
    if source_meta.get("id") != "pnas" and source_meta.get("publisher_family") != "pnas":
        return []
    channel = next((node for node in list(root) if local_name(node.tag) == "channel"), None)
    if channel is None:
        return []
    ch_title = child_text(channel, "title")
    if ":" not in ch_title:
        return []
    topic = ch_title.rsplit(":", 1)[-1].strip()
    if not topic or topic.lower() in {
        "table of contents",
        "proceedings of the national academy of sciences",
        "pnas",
    }:
        return []
    return [topic]


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


def first_doi(*values: Any) -> str:
    for value in values:
        doi = extract_doi(value)
        if doi:
            return doi
    return ""


def parse_feed_xml(xml_text: str, source_meta: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    root_name = local_name(root.tag)
    records: list[dict[str, Any]] = []
    if root_name == "RDF":
        channel_tags = extract_rdf_channel_tags(root, source_meta)
        is_pnas = source_meta.get("id") == "pnas" or source_meta.get("publisher_family") == "pnas"
        for item in root:
            if local_name(item.tag) != "item":
                continue
            categories = child_texts(item, "subject", "category")
            for tag in channel_tags:
                if tag not in categories:
                    categories.append(tag)
            links = child_texts(item, "link", "url")
            abstract = child_text(item, "encoded", "description", "summary")
            if is_pnas:
                abstract = clean_jats_abstract(abstract)
            published = child_text(item, "date", "published") or child_text(item, "coverDate")
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
                    "published": published,
                    "cover_date": child_text(item, "coverDate"),
                    "abstract": abstract,
                    "article_type": child_text(item, "type"),
                    "doi": first_doi(child_text(item, "doi", "identifier"), links[0] if links else ""),
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
                    "doi": first_doi(child_text(item, "doi", "identifier"), child_text(item, "link")),
                    "tags": categories,
                }
            )
    elif root_name == "feed":
        for entry in root:
            if local_name(entry.tag) != "entry":
                continue
            categories = [child.attrib.get("term", "").strip() for child in entry if local_name(child.tag) == "category" and child.attrib.get("term")]
            link = child_attr(entry, "link", "href") or child_text(entry, "link")
            doi = first_doi(child_text(entry, "doi", "identifier"), child_attr(entry, "link", "href"), child_text(entry, "link"))
            if not doi:
                entry_id = child_text(entry, "id")
                doi = first_doi(entry_id)
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
                "doi": extract_doi(link),
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
                "doi": extract_doi(link),
                "tags": [],
            }
        )
    return records


def extract_crossref_published(item: dict[str, Any]) -> str:
    for field in ("published-online", "published", "issued", "published-print"):
        date_parts = (item.get(field) or {}).get("date-parts") or []
        if date_parts and isinstance(date_parts[0], list) and len(date_parts[0]) >= 3:
            year, month, day = date_parts[0][:3]
            if isinstance(year, int) and isinstance(month, int) and isinstance(day, int):
                return f"{year:04d}-{month:02d}-{day:02d}T07:00:00Z"
    created_dt = (item.get("created") or {}).get("date-time")
    return str(created_dt or "").strip()


def extract_crossref_authors(item: dict[str, Any]) -> list[str]:
    authors: list[str] = []
    for author in item.get("author") or []:
        if not isinstance(author, dict):
            continue
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        full = f"{given} {family}".strip() or str(author.get("name") or "").strip()
        if full:
            authors.append(full)
    return authors


def parse_crossref_works_json(payload: str, source_meta: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    data = json.loads(payload)
    message = data.get("message") if isinstance(data, dict) else {}
    items = message.get("items") if isinstance(message, dict) else []
    if not isinstance(items, list):
        return []
    records: list[dict[str, Any]] = []
    is_pnas = source_meta.get("id") == "pnas" or source_meta.get("publisher_family") == "pnas"
    for item in items:
        if not isinstance(item, dict):
            continue
        doi = first_doi(item.get("DOI"))
        raw_titles = item.get("title") or []
        title = clean_inline_markup(" ".join(str(t) for t in raw_titles if t))
        if not title:
            continue
        if doi and doi.lower().startswith("10.1073/iti"):
            continue
        primary_url = ((item.get("resource") or {}).get("primary") or {}).get("URL")
        if is_pnas and doi:
            link = f"https://www.pnas.org/doi/abs/{doi}"
        else:
            link = str(primary_url or item.get("URL") or (f"https://doi.org/{doi}" if doi else "")).strip()
        subjects = [str(s).strip() for s in (item.get("subject") or []) if str(s).strip()]
        records.append(
            {
                "source_id": source_meta["id"],
                "journal": source_meta["journal_name"],
                "publisher_family": source_meta.get("publisher_family", ""),
                "group": source_meta.get("group", ""),
                "publication_stage": source_meta.get("publication_stage", "journal"),
                "source_url": source_url,
                "title": title,
                "link": link,
                "published": extract_crossref_published(item),
                "abstract": clean_jats_abstract(str(item.get("abstract") or "")),
                "article_type": str(item.get("type") or ""),
                "doi": doi,
                "tags": subjects,
                "authors": extract_crossref_authors(item),
            }
        )
    return records


def choose_cleaner_authors(existing: list[str], candidate: list[str]) -> list[str]:
    if not existing:
        return candidate
    if not candidate:
        return existing
    existing_has_ror = any("ror.org/" in a for a in existing)
    candidate_has_ror = any("ror.org/" in a for a in candidate)
    if existing_has_ror and not candidate_has_ror:
        return candidate
    if candidate_has_ror and not existing_has_ror:
        return existing
    return candidate if len(candidate) > len(existing) else existing


def merge_same_journal_records(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    existing_tags = list(existing.get("tags") or [])
    for tag in candidate.get("tags") or []:
        if tag and tag not in existing_tags:
            existing_tags.append(tag)
    merged["tags"] = existing_tags
    cand_abstract = str(candidate.get("abstract") or "").strip()
    exist_abstract = str(existing.get("abstract") or "").strip()
    if len(cand_abstract) > len(exist_abstract):
        merged["abstract"] = cand_abstract
    merged["authors"] = choose_cleaner_authors(
        list(existing.get("authors") or []),
        list(candidate.get("authors") or []),
    )
    if not merged.get("article_type") and candidate.get("article_type"):
        merged["article_type"] = candidate["article_type"]
    if not merged.get("doi") and candidate.get("doi"):
        merged["doi"] = candidate["doi"]
    return merged


def dedupe_journal_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records:
        doi = extract_doi(record.get("doi")) or extract_doi(record.get("link"))
        key = f"doi:{doi.lower()}" if doi else f"title:{str(record.get('title') or '').strip().lower()}"
        if key not in by_key:
            by_key[key] = record
            order.append(key)
        else:
            by_key[key] = merge_same_journal_records(by_key[key], record)
    return [by_key[k] for k in order]


def parse_source_payload(payload: str, source_meta: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    strategy = source_meta.get("source_strategy", "official_feed_or_toc")
    if "api.crossref.org/" in source_url or payload.lstrip().startswith("{"):
        return parse_crossref_works_json(payload, source_meta, source_url)
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
    parser.add_argument(
        "--retry-failed-with-proxy",
        action="store_true",
        help="Retry direct fetch or parse failures through a configured proxy.",
    )
    parser.add_argument(
        "--proxy-url",
        default="socks5h://127.0.0.1:40000",
        help="Proxy URL used with curl when --retry-failed-with-proxy is set.",
    )
    parser.add_argument("--curl-bin", default="curl", help="curl executable used for proxy retries.")
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
        failed_locators: list[tuple[str, str]] = []
        for locator in locator_list:
            try:
                parsed_records = fetch_and_parse_locator(
                    journal,
                    locator,
                    user_agent=args.user_agent,
                    timeout=args.timeout,
                    route="direct",
                    parse_payload=parse_source_payload,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[error] {journal['id']}: {exc}", file=sys.stderr)
                failed_locators.append((locator, f"{exc.__class__.__name__}: {exc}"))
                continue
            journal_records.extend(parsed_records)
        if args.retry_failed_with_proxy and failed_locators:
            for locator, direct_error in failed_locators:
                try:
                    parsed_records = fetch_and_parse_locator(
                        journal,
                        locator,
                        user_agent=args.user_agent,
                        timeout=args.timeout,
                        route="proxy",
                        parse_payload=parse_source_payload,
                        proxy_url=args.proxy_url,
                        curl_bin=args.curl_bin,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[proxy-error] {journal['id']}: {exc} "
                        f"(direct failure: {direct_error})",
                        file=sys.stderr,
                    )
                    continue
                journal_records.extend(parsed_records)
                print(f"[proxy-ok] {journal['id']}: recovered {len(parsed_records)} records", file=sys.stderr)
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
        deduped_records = dedupe_journal_records(filtered_records)
        journal_limit = int(journal.get("limit_per_journal") or args.limit_per_journal)
        output_records.extend(deduped_records[:journal_limit])
        print(f"[ok] {journal['id']}: {len(deduped_records[:journal_limit])} records", file=sys.stderr)

    write_jsonl(Path(args.output), output_records)
    print(
        f"Wrote {len(output_records)} raw records to {args.output} "
        f"from {len(selected_journals) - skipped_missing} configured sources.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
