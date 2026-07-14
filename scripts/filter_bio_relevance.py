#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from scripts.common import keyword_hits, load_watchlist, load_yaml_file, read_jsonl, safe_text_join, write_jsonl
except ModuleNotFoundError:
    from common import keyword_hits, load_watchlist, load_yaml_file, read_jsonl, safe_text_join, write_jsonl


def source_config(record: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, Any]:
    return watchlist.get("by_id", {}).get(record.get("source_id"), {})


def is_conditional_journal(record: dict[str, Any], rules: dict[str, Any], watchlist: dict[str, Any]) -> bool:
    conditional = set(rules.get("relevance_filter", {}).get("conditional_journals", []))
    return record.get("journal") in conditional or source_config(record, watchlist).get("group") == "ai-conditional"


def is_trusted_biology_source(record: dict[str, Any], filter_rules: dict[str, Any], watchlist: dict[str, Any]) -> bool:
    source_id = str(record.get("source_id", ""))
    group = str(source_config(record, watchlist).get("group", "") or record.get("group", ""))
    return source_id in set(filter_rules.get("trusted_biology_source_ids", [])) or group in set(
        filter_rules.get("trusted_biology_source_groups", [])
    )


def matches_pure_human_disease_exclusion(text: str, filter_rules: dict[str, Any]) -> tuple[bool, list[str]]:
    policy = filter_rules.get("pure_human_disease_exclusion", {})
    if not isinstance(policy, dict):
        return False, []
    if keyword_hits(text, policy.get("keep_override_keywords", [])):
        return False, []

    subject_hits = keyword_hits(text, policy.get("subject_keywords", []))
    disease_hits = keyword_hits(text, policy.get("disease_keywords", []))
    clinical_hits = keyword_hits(text, policy.get("clinical_context_keywords", []))
    matched = bool(subject_hits and disease_hits and clinical_hits)
    hits = [*subject_hits[:2], *disease_hits[:2], *clinical_hits[:3]] if matched else []
    return matched, hits


def matches_title_fragments(title: str, fragments: list[str] | tuple[str, ...] | Any) -> list[str]:
    lowered = title.lower()
    hits: list[str] = []
    for fragment in fragments or []:
        fragment_text = str(fragment).strip()
        if fragment_text and fragment_text.lower() in lowered:
            hits.append(fragment_text)
    return hits


def field_hits(record: dict[str, Any], keywords: list[str] | tuple[str, ...] | Any) -> dict[str, list[str]]:
    return {
        "title": keyword_hits(safe_text_join([record.get("title_en"), record.get("title_zh")]), keywords),
        "abstract": keyword_hits(safe_text_join([record.get("abstract")]), keywords),
        "tags": keyword_hits(safe_text_join([record.get("tags")]), keywords),
    }


def merge_hits(hit_groups: dict[str, list[str]]) -> list[str]:
    merged: list[str] = []
    for field_name in ("title", "tags", "abstract"):
        for hit in hit_groups.get(field_name, []):
            if hit not in merged:
                merged.append(hit)
    return merged


def weighted_hit_score(hit_groups: dict[str, list[str]], policy: dict[str, Any]) -> int:
    return sum(
        len(hit_groups.get(field_name, [])) * int(policy.get(f"{field_name}_weight", default_weight))
        for field_name, default_weight in (("title", 3), ("abstract", 1), ("tags", 2))
    )


def collect_evidence(record: dict[str, Any], filter_rules: dict[str, Any]) -> dict[str, Any]:
    policy = filter_rules.get("screening_policy", {})
    keep_by_field = field_hits(record, filter_rules.get("keep_keywords", []))
    priority_by_field = field_hits(record, filter_rules.get("priority_keep_keywords", []))
    ai_by_field = field_hits(record, filter_rules.get("ai_keep_keywords", []))
    anchors_by_field = field_hits(record, filter_rules.get("bio_anchor_keywords", []))
    reject_by_field = field_hits(record, filter_rules.get("reject_keywords", []))
    positive_score = weighted_hit_score(keep_by_field, policy) + weighted_hit_score(priority_by_field, policy)
    anchor_hits = merge_hits(anchors_by_field)
    ai_hits = merge_hits(ai_by_field)
    ai_requires_anchor = bool(policy.get("ai_requires_biology_anchor", True))
    if ai_hits and (anchor_hits or not ai_requires_anchor):
        positive_score += weighted_hit_score(ai_by_field, policy)
    return {
        "keep_by_field": keep_by_field,
        "priority_by_field": priority_by_field,
        "ai_by_field": ai_by_field,
        "anchors_by_field": anchors_by_field,
        "reject_by_field": reject_by_field,
        "keep_hits": merge_hits(keep_by_field),
        "priority_hits": merge_hits(priority_by_field),
        "ai_hits": ai_hits,
        "anchor_hits": anchor_hits,
        "reject_hits": merge_hits(reject_by_field),
        "positive_score": positive_score,
        "negative_score": weighted_hit_score(reject_by_field, policy),
    }


def decide_scored_relevance(
    record: dict[str, Any],
    filter_rules: dict[str, Any],
    watchlist: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[bool, str, bool]:
    policy = filter_rules.get("screening_policy", {})
    positive = int(evidence["positive_score"])
    negative = int(evidence["negative_score"])
    net_score = positive - negative
    keep_threshold = int(policy.get("keep_threshold", 3))
    review_threshold = int(policy.get("review_threshold", 1))
    conflict_margin = int(policy.get("conflict_margin", 2))
    strict = record.get("source_id", "") in set(filter_rules.get("strict_bio_source_ids", []))
    trusted = is_trusted_biology_source(record, filter_rules, watchlist)

    ai_requires_anchor = bool(policy.get("ai_requires_biology_anchor", True))
    if is_conditional_journal(record, {"relevance_filter": filter_rules}, watchlist) and ai_requires_anchor and not evidence["anchor_hits"]:
        if evidence["ai_hits"]:
            return False, "AI signal without biology anchor in conditional journal", False
        return False, "conditional journal without direct biology anchor", False
    if negative >= positive + conflict_margin:
        return False, f"negative evidence outweighs biology evidence: {', '.join(evidence['reject_hits'][:3])}", False
    if net_score >= keep_threshold:
        reason_hits = evidence["priority_hits"] or evidence["keep_hits"] or evidence["ai_hits"]
        review = bool(negative and positive - negative < keep_threshold + conflict_margin)
        return True, f"weighted biology evidence: {', '.join(reason_hits[:4])}", review
    if net_score >= review_threshold:
        reason_hits = evidence["priority_hits"] or evidence["keep_hits"] or evidence["anchor_hits"]
        if reason_hits:
            return True, f"borderline biology evidence: {', '.join(reason_hits[:4])}", True
        return True, "borderline biology evidence from trusted source prior", True
    if trusted:
        return True, "kept by trusted biology source scope", True
    if strict:
        return False, "strict bio source without sufficient biology evidence", False
    return True, "kept by default source scope", True


def evaluate_record(record: dict[str, Any], rules: dict[str, Any], watchlist: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    filter_rules = rules.get("relevance_filter", {})
    title = safe_text_join([record.get("title_en"), record.get("title_zh")])
    full_text = safe_text_join([title, record.get("abstract"), record.get("tags")]).lower()
    evidence = collect_evidence(record, filter_rules)
    source_prior = 0
    if is_trusted_biology_source(record, filter_rules, watchlist):
        source_prior = int(filter_rules.get("screening_policy", {}).get("source_prior_weight", 2))
        evidence["positive_score"] = int(evidence["positive_score"]) + source_prior
    hard_reject_hits = keyword_hits(full_text, filter_rules.get("hard_reject_keywords", []))
    manual_reject_hits = matches_title_fragments(title, filter_rules.get("manual_title_reject_fragments", []))
    clinical_exclusion, clinical_hits = matches_pure_human_disease_exclusion(full_text, filter_rules)
    doi = str(record.get("doi", "") or "").strip().lower()

    keep, reason, review_needed = decide_scored_relevance(record, filter_rules, watchlist, evidence)
    if any(title.lower().startswith(prefix.lower()) for prefix in filter_rules.get("editorial_reject_title_prefixes", [])):
        keep, reason, review_needed = False, "matched editorial title prefix", False
    elif manual_reject_hits:
        keep, reason, review_needed = False, f"matched manual title reject fragments: {', '.join(manual_reject_hits[:3])}", False
    elif any(doi.startswith(prefix.lower()) for prefix in filter_rules.get("editorial_reject_doi_prefixes", [])) and not evidence["positive_score"]:
        keep, reason, review_needed = False, "matched editorial DOI prefix without biology-specific signal", False
    elif hard_reject_hits:
        keep, reason, review_needed = False, f"matched hard reject keywords: {', '.join(hard_reject_hits[:3])}", False
    elif clinical_exclusion:
        reason = "matched pure human cancer or disease mechanism and high-confidence clinical disease scope"
        keep, reason, review_needed = False, f"{reason}: {', '.join(clinical_hits[:5])}", False

    annotated = dict(record)
    annotated.update(
        {
            "relevance_status": "keep" if keep else "reject",
            "relevance_reason": reason,
            "relevance_score": int(evidence["positive_score"]) - int(evidence["negative_score"]),
            "relevance_positive_score": evidence["positive_score"],
            "relevance_negative_score": evidence["negative_score"],
            "relevance_source_prior_score": source_prior,
            "relevance_keep_hits": evidence["keep_hits"],
            "relevance_priority_hits": evidence["priority_hits"],
            "relevance_ai_keep_hits": evidence["ai_hits"],
            "relevance_bio_anchor_hits": evidence["anchor_hits"],
            "relevance_reject_hits": evidence["reject_hits"],
            "relevance_hard_reject_hits": hard_reject_hits,
            "relevance_manual_title_reject_hits": manual_reject_hits,
            "relevance_human_disease_hits": clinical_hits,
            "relevance_review_needed": bool(keep and review_needed),
            "relevance_certainty": "review-needed" if keep and review_needed else "certain",
        }
    )
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
    evaluated = [evaluate_record(record, rules, watchlist) for record in records]
    write_jsonl(Path(args.output), [record for keep, record in evaluated if keep])
    write_jsonl(Path(args.rejected_output), [record for keep, record in evaluated if not keep])
    print(f"Kept {sum(keep for keep, _ in evaluated)} records and rejected {sum(not keep for keep, _ in evaluated)} records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
