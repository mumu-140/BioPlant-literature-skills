#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from scripts.common import keyword_hits, load_watchlist, load_yaml_file, read_jsonl, safe_text_join, write_jsonl
except ModuleNotFoundError:
    from common import keyword_hits, load_watchlist, load_yaml_file, read_jsonl, safe_text_join, write_jsonl


def is_conditional_journal(record: dict[str, Any], rules: dict[str, Any], watchlist: dict[str, Any]) -> bool:
    conditional = set(rules.get("relevance_filter", {}).get("conditional_journals", []))
    if record.get("journal") in conditional:
        return True
    source = watchlist.get("by_id", {}).get(record.get("source_id"), {})
    return source.get("group") == "ai-conditional"


def matches_pure_human_disease_exclusion(text: str, filter_rules: dict[str, Any]) -> tuple[bool, list[str]]:
    policy = filter_rules.get("pure_human_disease_exclusion", {})
    if not isinstance(policy, dict):
        return False, []

    keep_override_hits = keyword_hits(text, policy.get("keep_override_keywords", []))
    if keep_override_hits:
        return False, keep_override_hits

    subject_hits = keyword_hits(text, policy.get("subject_keywords", []))
    disease_hits = keyword_hits(text, policy.get("disease_keywords", []))
    mechanism_hits = keyword_hits(text, policy.get("mechanism_keywords", []))
    matched = bool(subject_hits and disease_hits and mechanism_hits)
    hits = [*subject_hits[:2], *disease_hits[:2], *mechanism_hits[:2]]
    return matched, hits


def matches_title_fragments(title: str, fragments: list[str] | tuple[str, ...] | Any) -> list[str]:
    lowered = title.lower()
    hits: list[str] = []
    for fragment in fragments or []:
        fragment_text = str(fragment).strip()
        if not fragment_text:
            continue
        if fragment_text.lower() in lowered:
            hits.append(fragment_text)
    return hits


def needs_ai_relevance_review(
    keep: bool,
    reason: str,
    *,
    keep_hits: list[str],
    ai_keep_hits: list[str],
    reject_hits: list[str],
    conditional: bool,
) -> bool:
    if not keep:
        return False
    reason_lower = reason.lower()
    if reason_lower.startswith("kept by default source scope"):
        return True
    if conditional and not ai_keep_hits:
        return True
    if reject_hits and (keep_hits or ai_keep_hits):
        return True
    return False


def evaluate_record(record: dict[str, Any], rules: dict[str, Any], watchlist: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    filter_rules = rules.get("relevance_filter", {})
    title = safe_text_join([record.get("title_en"), record.get("title_zh")])
    text = safe_text_join([record.get("title_en"), record.get("title_zh"), record.get("abstract"), record.get("tags")]).lower()
    title_lower = title.lower()
    keep_hits = keyword_hits(text, filter_rules.get("keep_keywords", []))
    ai_keep_hits = keyword_hits(text, filter_rules.get("ai_keep_keywords", []))
    reject_hits = keyword_hits(text, filter_rules.get("reject_keywords", []))
    hard_reject_hits = keyword_hits(text, filter_rules.get("hard_reject_keywords", []))
    manual_title_reject_hits = matches_title_fragments(title, filter_rules.get("manual_title_reject_fragments", []))
    pure_human_disease_exclusion, human_disease_hits = matches_pure_human_disease_exclusion(text, filter_rules)
    conditional = is_conditional_journal(record, rules, watchlist)
    doi = (record.get("doi") or "").strip().lower()
    source_id = record.get("source_id", "")

    keep = True
    reason = "kept by default source scope"
    if any(title_lower.startswith(prefix.lower()) for prefix in filter_rules.get("editorial_reject_title_prefixes", [])):
        keep = False
        reason = "matched editorial title prefix"
    elif manual_title_reject_hits:
        keep = False
        reason = f"matched manual title reject fragments: {', '.join(manual_title_reject_hits[:3])}"
    elif (
        any(doi.startswith(prefix.lower()) for prefix in filter_rules.get("editorial_reject_doi_prefixes", []))
        and not (keep_hits or ai_keep_hits)
    ):
        keep = False
        reason = "matched editorial DOI prefix without biology-specific signal"
    elif hard_reject_hits:
        keep = False
        reason = f"matched hard reject keywords: {', '.join(hard_reject_hits[:3])}"
    elif pure_human_disease_exclusion:
        keep = False
        reason = f"matched pure human cancer or disease mechanism scope: {', '.join(human_disease_hits[:4])}"
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
    annotated["relevance_manual_title_reject_hits"] = manual_title_reject_hits
    annotated["relevance_human_disease_hits"] = human_disease_hits
    review_needed = needs_ai_relevance_review(
        keep,
        reason,
        keep_hits=keep_hits,
        ai_keep_hits=ai_keep_hits,
        reject_hits=reject_hits,
        conditional=conditional,
    )
    annotated["relevance_review_needed"] = review_needed
    annotated["relevance_certainty"] = "review-needed" if review_needed else "certain"
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
