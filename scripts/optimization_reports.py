#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SRC_DIR = SKILL_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bio_literature_digest.reports.optimization import (  # noqa: E402
    generate_classification_suggestions,
    generate_glossary_candidates,
    generate_rule_feedback_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate optimization-oriented reports used by the digest pipeline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rule_feedback = subparsers.add_parser(
        "rule-feedback",
        help="Summarize rule-vs-LLM review outcomes for rule tuning.",
    )
    rule_feedback.add_argument("--input", required=True, help="Reviewed audit JSONL")
    rule_feedback.add_argument("--output", required=True, help="Markdown feedback report")

    classify = subparsers.add_parser(
        "classification-suggestions",
        help="Build daily classification optimization suggestions.",
    )
    classify.add_argument("--classified", required=True, help="Classified records JSONL")
    classify.add_argument("--reviewed", required=True, help="Reviewed records JSONL")
    classify.add_argument("--markdown-output", required=True, help="Markdown report path")
    classify.add_argument("--json-output", required=True, help="JSON suggestions path")

    glossary = subparsers.add_parser(
        "glossary-candidates",
        help="Build daily glossary candidates from digest records.",
    )
    glossary.add_argument("--input", required=True, help="Localized digest JSONL")
    glossary.add_argument("--glossary", required=True, help="Path to glossary YAML")
    glossary.add_argument("--yaml-output", required=True, help="Candidate YAML output path")
    glossary.add_argument("--report-output", required=True, help="Candidate markdown report output path")
    glossary.add_argument("--max-candidates", type=int, default=50)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "rule-feedback":
        count = generate_rule_feedback_report(args.input, args.output)
        print(f"Wrote rule feedback report for {count} reviewed records.")
        return 0

    if args.command == "classification-suggestions":
        count = generate_classification_suggestions(
            args.classified,
            args.reviewed,
            args.markdown_output,
            args.json_output,
        )
        print(f"Built classification suggestions for {count} classified records.")
        return 0

    if args.command == "glossary-candidates":
        count = generate_glossary_candidates(
            args.input,
            args.glossary,
            args.yaml_output,
            args.report_output,
            max_candidates=args.max_candidates,
        )
        print(f"Built {count} glossary candidates.")
        return 0

    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
