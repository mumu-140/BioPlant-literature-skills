#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import load_yaml_file, read_jsonl


TERM_PATTERN = re.compile(r"\b[a-z][a-z0-9-]{2,}(?:\s+[a-z0-9-]{2,}){0,3}\b", re.IGNORECASE)


def normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())


def existing_terms(glossary: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for item in glossary.get("replacements", []):
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if source:
            terms.add(normalize_term(source))
        if target:
            terms.add(normalize_term(target))
    for term in glossary.get("candidate_seed_terms", []):
        terms.add(normalize_term(str(term)))
    return terms


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily glossary candidates from digest records.")
    parser.add_argument("--input", required=True, help="Localized digest JSONL")
    parser.add_argument("--glossary", required=True, help="Path to glossary YAML")
    parser.add_argument("--yaml-output", required=True, help="Candidate YAML output path")
    parser.add_argument("--report-output", required=True, help="Candidate markdown report output path")
    parser.add_argument("--max-candidates", type=int, default=50)
    args = parser.parse_args()

    records = read_jsonl(Path(args.input))
    glossary = load_yaml_file(args.glossary) or {}
    known_terms = existing_terms(glossary if isinstance(glossary, dict) else {})
    seed_terms = [normalize_term(str(term)) for term in (glossary.get("candidate_seed_terms", []) if isinstance(glossary, dict) else [])]

    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for record in records:
        text = " ".join(
            [
                str(record.get("title_en", "")),
                str(record.get("abstract", "")),
                " ".join(str(item) for item in record.get("tags", [])),
            ]
        )
        lowered = text.lower()
        for seed in seed_terms:
            if seed and seed not in known_terms and seed in lowered:
                counts[seed] += 1
                if len(examples[seed]) < 3:
                    examples[seed].append(str(record.get("title_en", "")))
        for match in TERM_PATTERN.findall(lowered):
            term = normalize_term(match)
            if term in known_terms or len(term) < 4:
                continue
            if any(ch.isdigit() for ch in term) and term.count(" ") > 1:
                continue
            if term in {"with", "from", "through", "during", "under", "between", "using"}:
                continue
            counts[term] += 1
            if len(examples[term]) < 2:
                examples[term].append(str(record.get("title_en", "")))

    ranked = []
    for term, count in counts.most_common(args.max_candidates):
        ranked.append(
            {
                "source": term,
                "target": "",
                "count": count,
                "examples": examples.get(term, []),
            }
        )

    yaml_payload = {"candidates": ranked}
    Path(args.yaml_output).write_text(json.dumps(yaml_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "# Glossary Candidate Report",
        "",
        f"- Total candidates: {len(ranked)}",
        "",
    ]
    for item in ranked:
        report_lines.append(f"## {item['source']} ({item['count']})")
        for example in item["examples"]:
            report_lines.append(f"- {example}")
        report_lines.append("")
    Path(args.report_output).write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Built {len(ranked)} glossary candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
