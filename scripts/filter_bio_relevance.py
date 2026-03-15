#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import keyword_hits, load_watchlist, load_yaml_file, read_jsonl, safe_text_join, write_jsonl


def is_conditional_journal(record: dict[str, Any], rules: dict[str, Any], watchlist: dict[str, Any]) -> bool:
    conditional = set(rules.get("relevance_filter", {}).get("conditional_journals", []))
    if record.get("journal") in conditional:
        return True
    source = watchlist.get("by_id", {}).get(record.get("source_id"), {})
    return source.get("group") == "ai-conditional"


def evaluate_record(record: dict[str, Any], rules: dict[str, Any], watchlist: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    filter_rules = rules.get("relevance_filter", {})
    text = safe_text_join([record.get("journal"), record.get("title_en"), record.get("abstract"), record.get("tags")]).lower()
    keep_hits = keyword_hits(text, filter_rules.get("keep_keywords", []))
    ai_keep_hits = keyword_hits(text, filter_rules.get("ai_keep_keywords", []))
    reject_hits = keyword_hits(text, filter_rules.get("reject_keywords", []))
    hard_reject_hits = keyword_hits(text, filter_rules.get("hard_reject_keywords", []))
    conditional = is_conditional_journal(record, rules, watchlist)
    title = (record.get("title_en") or "").strip()
    doi = (record.get("doi") or "").strip().lower()
    source_id = record.get("source_id", "")

    keep = True
    reason = "kept by default source scope"
    if any(title.startswith(prefix) for prefix in filter_rules.get("editorial_reject_title_prefixes", [])):
        keep = False
        reason = "matched editorial title prefix"
    elif any(doi.startswith(prefix.lower()) for prefix in filter_rules.get("editorial_reject_doi_prefixes", [])):
        keep = False
        reason = "matched editorial DOI prefix"
    elif hard_reject_hits:
        keep = False
        reason = f"matched hard reject keywords: {', '.join(hard_reject_hits[:3])}"
    elif ai_keep_hits:
        reason = f"matched AI keep keywords: {', '.join(ai_keep_hits[:3])}"
    elif conditional and not keep_hits:
        keep = False
        reason = "conditional journal without biology-specific signal"
    elif source_id in set(filter_rules.get("strict_bio_source_ids", [])) and not keep_hits:
        keep = False
        reason = "strict bio source without biology-specific keyword match"
    elif reject_hits and not keep_hits:
        keep = False
        reason = f"matched reject keywords: {', '.join(reject_hits[:3])}"
    elif len(reject_hits) > len(keep_hits) + 1:
        keep = False
        reason = f"reject signals outweigh keep signals: {', '.join(reject_hits[:3])}"
    elif keep_hits:
        reason = f"matched keep keywords: {', '.join(keep_hits[:3])}"

    annotated = dict(record)
    annotated["relevance_status"] = "keep" if keep else "reject"
    annotated["relevance_reason"] = reason
    annotated["relevance_keep_hits"] = keep_hits
    annotated["relevance_ai_keep_hits"] = ai_keep_hits
    annotated["relevance_reject_hits"] = reject_hits
    annotated["relevance_hard_reject_hits"] = hard_reject_hits
    return keep, annotated


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter normalized records for biology relevance.")
    parser.add_argument("--input", required=True, help="Normalized input JSONL")
    parser.add_argument("--rules", required=True, help="Path to category_rules.yaml")
    parser.add_argument("--watchlist", required=True, help="Path to journal_watchlist.yaml")
    parser.add_argument("--output", required=True, help="Kept records JSONL")
    parser.add_argument("--rejected-output", required=True, help="Rejected records JSONL")
    args = parser.parse_args()

    records = read_jsonl(Path(args.input))
    rules = load_yaml_file(args.rules) or {}
    watchlist = load_watchlist(args.watchlist)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for record in records:
        keep, annotated = evaluate_record(record, rules, watchlist)
        if keep:
            kept.append(annotated)
        else:
            rejected.append(annotated)

    write_jsonl(Path(args.output), kept)
    write_jsonl(Path(args.rejected_output), rejected)
    print(f"Kept {len(kept)} records and rejected {len(rejected)} records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
