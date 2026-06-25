from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from bio_literature_digest.review.backlog import review_record_key


GENERIC_TERMS = {
    "study",
    "result",
    "results",
    "analysis",
    "model",
    "models",
    "method",
    "methods",
    "system",
    "systems",
    "cell",
    "cells",
    "protein",
    "gene",
}


def read_text(path: Path, limit: int = 6000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_sample(path: Path, limit: int = 30) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{key: str(value or "") for key, value in row.items()} for row in list(csv.DictReader(handle))[:limit]]


def backlog_key(row: dict[str, str]) -> dict[str, str]:
    key_kind, key_value = review_record_key(row)
    return {
        "digest_date": str(row.get("digest_date", "")).strip(),
        "key_kind": key_kind,
        "key_value": key_value,
    }


def compact_review_row(row: dict[str, str], index: int) -> dict[str, str]:
    keep_fields = [
        "source_id",
        "journal",
        "category",
        "interest_level",
        "interest_tag",
        "title_en",
        "title_zh",
        "summary_zh",
        "abstract",
        "doi",
        "article_url",
        "tags",
        "llm_decision",
        "llm_reason",
        "review_final_decision",
        "review_final_category",
        "reviewer_notes",
        "admission_tier",
        "admission_reason",
    ]
    payload = {"row_index": str(index), **backlog_key(row)}
    payload.update({field: str(row.get(field, "")).strip() for field in keep_fields})
    return payload


def normalize_term(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def row_text(row: dict[str, str]) -> str:
    fields = ["title_en", "abstract", "tags", "reviewer_notes", "summary_zh", "title_zh"]
    return " ".join(str(row.get(field, "") or "") for field in fields).lower()


def term_allowed(term: str, row: dict[str, str]) -> bool:
    normalized = normalize_term(term)
    lowered = normalized.lower()
    if len(lowered) < 4 or len(lowered) > 90 or lowered in GENERIC_TERMS:
        return False
    return lowered in row_text(row)


def add_unique(items: list[Any], value: Any, key_fn) -> bool:
    existing = {key_fn(item) for item in items}
    key = key_fn(value)
    if not key or key in existing:
        return False
    items.append(value)
    return True


def iter_update_items(container: Any, name: str) -> list[dict[str, Any]]:
    raw_items = container.get(name, []) if isinstance(container, dict) else []
    if not isinstance(raw_items, list):
        return []
    return [{"keyword": str(item)} if isinstance(item, str) else item for item in raw_items if isinstance(item, (str, dict))]
