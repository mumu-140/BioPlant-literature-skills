#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from common import ensure_parent_dir, read_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize rule-vs-LLM review outcomes for rule tuning.")
    parser.add_argument("--input", required=True, help="Reviewed audit JSONL")
    parser.add_argument("--output", required=True, help="Markdown feedback report")
    args = parser.parse_args()

    records = read_jsonl(Path(args.input))
    total = len(records)
    decision_counts = Counter(record.get("final_decision", "unknown") for record in records)
    source_counts = Counter(record.get("source_id", "") for record in records if record.get("final_decision") != "keep")

    rule_keep_llm_review = [record for record in records if record.get("rule_decision") == "keep" and record.get("llm_decision") == "review"]
    rule_keep_llm_reject = [record for record in records if record.get("rule_decision") == "keep" and record.get("llm_decision") == "reject"]
    category_override = [record for record in records if record.get("llm_category_override")]

    lines = [
        "# Rule Feedback Report",
        "",
        f"- Total reviewed: {total}",
        f"- Keep: {decision_counts.get('keep', 0)}",
        f"- Review: {decision_counts.get('review', 0)}",
        f"- Reject: {decision_counts.get('reject', 0)}",
        "",
        "## Rule Keep But LLM Review",
    ]
    if rule_keep_llm_review:
        for record in rule_keep_llm_review[:10]:
            lines.append(
                f"- `{record.get('source_id', '')}` `{record.get('category', '')}` "
                f"{record.get('title_en', '')} | {record.get('llm_reason', '')}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Rule Keep But LLM Reject"])
    if rule_keep_llm_reject:
        for record in rule_keep_llm_reject[:10]:
            lines.append(
                f"- `{record.get('source_id', '')}` {record.get('title_en', '')} | "
                f"{record.get('llm_reason', '')}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Category Overrides"])
    if category_override:
        for record in category_override[:10]:
            lines.append(
                f"- `{record.get('source_id', '')}` `{record.get('category_original', '')}` -> "
                f"`{record.get('llm_category_override', '')}` | {record.get('title_en', '')}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Sources With Most Non-Keep Decisions"])
    if source_counts:
        for source_id, count in source_counts.most_common(10):
            lines.append(f"- `{source_id}`: {count}")
    else:
        lines.append("- None")

    ensure_parent_dir(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote rule feedback report for {total} reviewed records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
