#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import keyword_hits, load_yaml_file, read_jsonl, safe_text_join, write_jsonl


def classify_record(record: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    categories = rules.get("categories", [])
    text = safe_text_join([record.get("journal"), record.get("title_en"), record.get("abstract"), record.get("tags")]).lower()
    scored: list[tuple[int, str, list[str]]] = []
    for category in categories:
        category_id = category.get("id")
        if category_id == "other":
            continue
        hits = keyword_hits(text, category.get("keywords", []))
        scored.append((len(hits), category_id, hits))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    category_id = rules.get("classification_policy", {}).get("fallback_category", "other")
    reason = "no category keyword matched"
    hits: list[str] = []
    if scored and scored[0][0] > 0:
        _, category_id, hits = scored[0]
        reason = f"matched category keywords: {', '.join(hits[:4])}"

    annotated = dict(record)
    annotated["category"] = category_id
    annotated["category_reason"] = reason
    annotated["category_hits"] = hits
    return annotated


def main() -> int:
    parser = argparse.ArgumentParser(description="Assign a single fixed category to each retained paper.")
    parser.add_argument("--input", required=True, help="Filtered records JSONL")
    parser.add_argument("--rules", required=True, help="Path to category_rules.yaml")
    parser.add_argument("--output", required=True, help="Classified records JSONL")
    args = parser.parse_args()

    records = read_jsonl(Path(args.input))
    rules = load_yaml_file(args.rules) or {}
    output = [classify_record(record, rules) for record in records]
    write_jsonl(Path(args.output), output)
    print(f"Classified {len(output)} records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
