#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from scripts.common import keyword_hits, load_yaml_file, read_jsonl, safe_text_join, write_jsonl
except ModuleNotFoundError:
    from common import keyword_hits, load_yaml_file, read_jsonl, safe_text_join, write_jsonl


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


def weighted_score(hit_groups: dict[str, list[str]], policy: dict[str, Any]) -> int:
    return sum(
        len(hit_groups.get(field_name, [])) * int(policy.get(f"{field_name}_weight", default_weight))
        for field_name, default_weight in (("title", 3), ("abstract", 1), ("tags", 2))
    )


def score_category(record: dict[str, Any], category: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    keyword_groups = field_hits(record, category.get("keywords", []))
    priority_groups = field_hits(record, category.get("priority_keywords", []))
    negative_groups = field_hits(record, category.get("negative_keywords", []))
    priority_multiplier = int(policy.get("priority_keyword_multiplier", 2))
    score = weighted_score(keyword_groups, policy)
    score += weighted_score(priority_groups, policy) * priority_multiplier
    score -= weighted_score(negative_groups, policy)

    source_id = str(record.get("source_id", ""))
    source_group = str(record.get("group", ""))
    if source_id and source_id in set(category.get("source_ids", [])):
        score += int(policy.get("source_prior_weight", 2))
    if source_group and source_group in set(category.get("source_groups", [])):
        score += int(policy.get("source_prior_weight", 2))
    return {
        "category": category.get("id", "other"),
        "score": score,
        "hits": merge_hits(keyword_groups),
        "priority_hits": merge_hits(priority_groups),
        "negative_hits": merge_hits(negative_groups),
    }


def classify_record(record: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    categories = [category for category in rules.get("categories", []) if category.get("id") != "other"]
    classification = rules.get("classification_policy", {})
    scoring_policy = classification.get("scoring", {})
    ranked = [score_category(record, category, scoring_policy) for category in categories]
    order = {category.get("id"): index for index, category in enumerate(categories)}
    ranked.sort(key=lambda item: (-int(item["score"]), order.get(item["category"], len(order))))

    fallback = classification.get("fallback_category", "other")
    minimum_score = int(scoring_policy.get("minimum_score", 2))
    review_margin = int(scoring_policy.get("review_margin", 2))
    top = ranked[0] if ranked else {"category": fallback, "score": 0, "hits": [], "priority_hits": []}
    runner_up_score = int(ranked[1]["score"]) if len(ranked) > 1 else 0
    category_id = str(top["category"]) if int(top["score"]) >= minimum_score else fallback
    margin = int(top["score"]) - runner_up_score
    hits = list(top.get("priority_hits", [])) + [hit for hit in top.get("hits", []) if hit not in top.get("priority_hits", [])]
    reason = "no category reached minimum evidence score"
    if category_id != fallback:
        reason = f"weighted category evidence ({top['score']}): {', '.join(hits[:5])}"

    annotated = dict(record)
    annotated.update(
        {
            "category": category_id,
            "category_reason": reason,
            "category_hits": hits,
            "category_score": int(top["score"]) if category_id != fallback else 0,
            "category_margin": margin if category_id != fallback else 0,
            "category_review_needed": bool(category_id == fallback or margin <= review_margin),
            "category_scores": ranked[:5],
        }
    )
    return annotated


def main() -> int:
    parser = argparse.ArgumentParser(description="Assign a single fixed category to each retained paper.")
    parser.add_argument("--input", required=True, help="Filtered records JSONL")
    parser.add_argument("--rules", required=True, help="Path to category_rules.yaml")
    parser.add_argument("--output", required=True, help="Classified records JSONL")
    args = parser.parse_args()

    records = read_jsonl(Path(args.input))
    rules = load_yaml_file(args.rules) or {}
    write_jsonl(Path(args.output), [classify_record(record, rules) for record in records])
    print(f"Classified {len(records)} records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
