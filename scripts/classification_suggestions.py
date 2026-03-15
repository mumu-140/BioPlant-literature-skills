#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import ensure_parent_dir, read_jsonl


def token_candidates(record: dict[str, Any]) -> list[str]:
    title = str(record.get("title_en", "")).lower()
    abstract = str(record.get("abstract", "")).lower()
    text = f"{title} {abstract}"
    tokens: list[str] = []
    for token in [
        "microbiome",
        "microbiota",
        "rhizosphere",
        "phyllosphere",
        "auxin",
        "cytokinin",
        "gibberellin",
        "stomata",
        "guard cell",
        "federated learning",
        "macrophage",
        "chondrocyte",
        "mitosis",
        "glioma",
        "oxidative stress",
        "circadian",
        "bile acid",
        "imaging",
        "diagnosis",
        "cancer",
        "brain",
        "neural",
    ]:
        if token in text:
            tokens.append(token)
    return tokens


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily classification optimization suggestions.")
    parser.add_argument("--classified", required=True, help="Classified records JSONL")
    parser.add_argument("--reviewed", required=True, help="Reviewed records JSONL")
    parser.add_argument("--markdown-output", required=True, help="Markdown report path")
    parser.add_argument("--json-output", required=True, help="JSON suggestions path")
    args = parser.parse_args()

    classified = read_jsonl(Path(args.classified))
    reviewed = read_jsonl(Path(args.reviewed))

    other_records = [record for record in classified if (record.get("category") or "") == "other"]
    review_records = [record for record in reviewed if (record.get("final_decision") or "") == "review"]
    reject_records = [record for record in reviewed if (record.get("final_decision") or "") == "reject"]

    source_other = Counter(record.get("source_id", "") for record in other_records)
    source_review = Counter(record.get("source_id", "") for record in review_records)
    token_counts: Counter[str] = Counter()
    token_examples: dict[str, list[str]] = defaultdict(list)
    for record in other_records + review_records:
        for token in token_candidates(record):
            token_counts[token] += 1
            if len(token_examples[token]) < 3:
                token_examples[token].append(str(record.get("title_en", "")))

    suggestions = {
        "source_other_counts": dict(source_other.most_common(20)),
        "source_review_counts": dict(source_review.most_common(20)),
        "token_suggestions": [
            {"token": token, "count": count, "examples": token_examples[token]}
            for token, count in token_counts.most_common(30)
        ],
        "review_examples": [
            {
                "source_id": record.get("source_id", ""),
                "title_en": record.get("title_en", ""),
                "llm_reason": record.get("llm_reason", ""),
            }
            for record in review_records[:20]
        ],
        "reject_examples": [
            {
                "source_id": record.get("source_id", ""),
                "title_en": record.get("title_en", ""),
                "llm_reason": record.get("llm_reason", ""),
            }
            for record in reject_records[:20]
        ],
    }

    lines = [
        "# Classification Suggestions Report",
        "",
        f"- Other category count: {len(other_records)}",
        f"- Review count: {len(review_records)}",
        f"- Reject count: {len(reject_records)}",
        "",
        "## Sources With Most `other` Records",
    ]
    if source_other:
        for source_id, count in source_other.most_common(10):
            lines.append(f"- `{source_id}`: {count}")
    else:
        lines.append("- None")
    lines.extend(["", "## Sources With Most Review Records"])
    if source_review:
        for source_id, count in source_review.most_common(10):
            lines.append(f"- `{source_id}`: {count}")
    else:
        lines.append("- None")
    lines.extend(["", "## Suggested Tokens To Consider For Category Rules"])
    if token_counts:
        for token, count in token_counts.most_common(20):
            lines.append(f"- `{token}` ({count})")
            for example in token_examples[token]:
                lines.append(f"  - {example}")
    else:
        lines.append("- None")
    lines.extend(["", "## Review Examples"])
    if review_records:
        for record in review_records[:10]:
            lines.append(f"- `{record.get('source_id', '')}` {record.get('title_en', '')} | {record.get('llm_reason', '')}")
    else:
        lines.append("- None")

    ensure_parent_dir(args.markdown_output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    ensure_parent_dir(args.json_output).write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built classification suggestions for {len(classified)} classified records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
