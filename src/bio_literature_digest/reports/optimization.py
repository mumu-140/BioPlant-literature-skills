from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from bio_literature_digest.config.runtime import expand_config_value


TERM_PATTERN = re.compile(r"\b[a-z][a-z0-9-]{2,}(?:\s+[a-z0-9-]{2,}){0,3}\b", re.IGNORECASE)


def ensure_parent_dir(path: str | Path) -> Path:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    return path_obj


def load_yaml_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


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


def build_classification_suggestions(
    classified: list[dict[str, Any]],
    reviewed: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
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
    return suggestions, "\n".join(lines) + "\n"


def build_rule_feedback_report(records: list[dict[str, Any]]) -> str:
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
    return "\n".join(lines) + "\n"


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


def build_glossary_candidates(
    records: list[dict[str, Any]],
    glossary: dict[str, Any],
    *,
    max_candidates: int = 50,
) -> tuple[dict[str, Any], str]:
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
    for term, count in counts.most_common(max_candidates):
        ranked.append(
            {
                "source": term,
                "target": "",
                "count": count,
                "examples": examples.get(term, []),
            }
        )

    yaml_payload = {"candidates": ranked}
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
    return yaml_payload, "\n".join(report_lines)


def load_glossary(path: str | Path) -> dict[str, Any]:
    loaded = load_yaml_file(expand_config_value(path)) or {}
    return loaded if isinstance(loaded, dict) else {}


def read_jsonl_records(path: str | Path) -> list[dict[str, Any]]:
    return read_jsonl(Path(path))


def write_markdown(path: str | Path, content: str) -> None:
    ensure_parent_dir(path).write_text(content, encoding="utf-8")


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    ensure_parent_dir(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_rule_feedback_report(input_path: str | Path, output_path: str | Path) -> int:
    records = read_jsonl_records(input_path)
    write_markdown(output_path, build_rule_feedback_report(records))
    return len(records)


def generate_classification_suggestions(
    classified_path: str | Path,
    reviewed_path: str | Path,
    markdown_output_path: str | Path,
    json_output_path: str | Path,
) -> int:
    classified = read_jsonl_records(classified_path)
    reviewed = read_jsonl_records(reviewed_path)
    suggestions, markdown = build_classification_suggestions(classified, reviewed)
    write_markdown(markdown_output_path, markdown)
    write_json(json_output_path, suggestions)
    return len(classified)


def generate_glossary_candidates(
    input_path: str | Path,
    glossary_path: str | Path,
    yaml_output_path: str | Path,
    report_output_path: str | Path,
    *,
    max_candidates: int = 50,
) -> int:
    records = read_jsonl_records(input_path)
    glossary = load_glossary(glossary_path)
    payload, markdown = build_glossary_candidates(records, glossary, max_candidates=max_candidates)
    write_json(yaml_output_path, payload)
    write_markdown(report_output_path, markdown)
    return len(payload.get("candidates", []))
