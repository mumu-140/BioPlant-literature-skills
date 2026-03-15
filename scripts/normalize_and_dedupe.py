#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import (
    canonicalize_doi,
    canonicalize_url,
    count_nonempty_fields,
    isoformat_utc,
    normalize_title,
    normalize_whitespace,
    parse_datetime_guess,
    read_jsonl,
    within_utc_window,
    write_jsonl,
)


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    title_en = normalize_whitespace(raw.get("title") or raw.get("title_en"))
    abstract = normalize_whitespace(raw.get("abstract") or raw.get("summary") or raw.get("description"))
    article_url = canonicalize_url(raw.get("link") or raw.get("article_url") or raw.get("url"))
    published_dt = parse_datetime_guess(raw.get("published_at") or raw.get("published") or raw.get("date"))
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {
        "source_id": raw.get("source_id", ""),
        "journal": normalize_whitespace(raw.get("journal")),
        "publisher_family": raw.get("publisher_family", ""),
        "group": raw.get("group", ""),
        "publication_stage": normalize_whitespace(raw.get("publication_stage")) or "journal",
        "article_type": normalize_whitespace(raw.get("article_type")),
        "title_en": title_en,
        "title_norm": normalize_title(title_en),
        "doi": canonicalize_doi(raw.get("doi")),
        "article_url": raw.get("link") or raw.get("article_url") or raw.get("url") or "",
        "canonical_url": article_url,
        "published_at": isoformat_utc(published_dt),
        "abstract": abstract,
        "tags": [normalize_whitespace(tag) for tag in tags if normalize_whitespace(tag)],
        "authors": raw.get("authors") or [],
        "source_url": raw.get("source_url", ""),
        "fetched_at": raw.get("fetched_at", ""),
    }


def dedupe_key(record: dict[str, Any]) -> str:
    if record["doi"]:
        return f"doi:{record['doi']}"
    if record["canonical_url"]:
        return f"url:{record['canonical_url']}"
    return f"title:{record['journal'].lower()}::{record['title_norm']}"


def dedupe_candidates(record: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    if record["canonical_url"]:
        candidates.append(f"url:{record['canonical_url']}")
    if record["doi"]:
        candidates.append(f"doi:{record['doi']}")
    candidates.append(f"title:{record['journal'].lower()}::{record['title_norm']}")
    return candidates


def choose_better(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    existing_score = count_nonempty_fields(existing)
    candidate_score = count_nonempty_fields(candidate)
    if candidate_score != existing_score:
        return candidate_score > existing_score
    return candidate.get("published_at", "") < existing.get("published_at", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize raw records and remove duplicates.")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--output", required=True, help="Normalized output JSONL file")
    parser.add_argument("--duplicates-output", help="Optional JSONL file for dropped duplicates")
    parser.add_argument("--lookback-hours", type=int, default=None, help="Keep only records published within this many hours")
    parser.add_argument("--window-start", help="Inclusive UTC window start in ISO-8601 format")
    parser.add_argument("--window-end", help="Inclusive UTC window end in ISO-8601 format")
    args = parser.parse_args()

    raw_records = read_jsonl(Path(args.input))
    best_by_key: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    duplicates: list[dict[str, Any]] = []
    skipped_missing_published = 0
    skipped_old = 0
    cutoff = None
    window_start = parse_datetime_guess(args.window_start) if args.window_start else None
    window_end = parse_datetime_guess(args.window_end) if args.window_end else None
    if args.lookback_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=args.lookback_hours)

    for raw_record in raw_records:
        normalized = normalize_record(raw_record)
        if window_start is not None or window_end is not None:
            published_dt = parse_datetime_guess(normalized.get("published_at"))
            if published_dt is None:
                skipped_missing_published += 1
                continue
            if not within_utc_window(published_dt, window_start, window_end):
                skipped_old += 1
                continue
        elif cutoff is not None:
            published_dt = parse_datetime_guess(normalized.get("published_at"))
            if published_dt is None:
                skipped_missing_published += 1
                continue
            if published_dt < cutoff:
                skipped_old += 1
                continue
        candidates = dedupe_candidates(normalized)
        key = next((aliases[candidate] for candidate in candidates if candidate in aliases), dedupe_key(normalized))
        previous = best_by_key.get(key)
        if previous is None:
            best_by_key[key] = normalized
            for candidate in candidates:
                aliases[candidate] = key
            continue
        if choose_better(previous, normalized):
            duplicates.append(previous | {"duplicate_of": key})
            best_by_key[key] = normalized
            for candidate in dedupe_candidates(normalized):
                aliases[candidate] = key
            for candidate in dedupe_candidates(previous):
                aliases[candidate] = key
        else:
            duplicates.append(normalized | {"duplicate_of": key})
            for candidate in candidates:
                aliases[candidate] = key

    normalized_records = list(best_by_key.values())
    normalized_records.sort(key=lambda item: (item.get("published_at", ""), item.get("journal", ""), item.get("title_en", "")), reverse=True)
    write_jsonl(Path(args.output), normalized_records)
    if args.duplicates_output:
        write_jsonl(Path(args.duplicates_output), duplicates)
    if window_start is not None or window_end is not None:
        print(
            f"Normalized {len(raw_records)} records into {len(normalized_records)} unique items. "
            f"Skipped {skipped_missing_published} without publish_date and {skipped_old} outside window."
        )
    elif cutoff is not None:
        print(
            f"Normalized {len(raw_records)} records into {len(normalized_records)} unique items. "
            f"Skipped {skipped_missing_published} without publish_date and {skipped_old} older than {args.lookback_hours}h."
        )
    else:
        print(f"Normalized {len(raw_records)} records into {len(normalized_records)} unique items.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
