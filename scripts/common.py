#!/usr/bin/env python3
"""Shared helpers for the digest pipeline scripts.

Identity normalization and digest-window computation now live in the package
tree (``bio_literature_digest.identity`` / ``bio_literature_digest.scheduling``)
so that ``scripts/*`` and ``src/*`` share a single implementation. They are
re-exported here unchanged: every existing ``from common import ...`` keeps
working.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

_SKILL_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _SKILL_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from bio_literature_digest.identity.normalize import (  # noqa: E402
    DOI_PATTERN,
    TRACKING_QUERY_KEYS,
    TRACKING_QUERY_PREFIXES,
    canonicalize_doi,
    canonicalize_url,
    extract_doi,
    normalize_title,
    normalize_whitespace,
)
from bio_literature_digest.scheduling.window import (  # noqa: E402
    compute_scheduled_digest_window,
    current_timestamp_utc,
    isoformat_utc,
    parse_clock_hhmm,
    parse_datetime_guess,
    within_utc_window,
)


def ensure_parent_dir(path: str | Path) -> Path:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    return path_obj


def load_yaml_file(path: str | Path) -> Any:
    path_obj = Path(path)
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required. Install dependencies with `pip install -r requirements.txt`.") from exc

    with path_obj.open("r", encoding="utf-8") as handle:
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


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    path_obj = ensure_parent_dir(path)
    with path_obj.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def count_nonempty_fields(record: dict[str, Any]) -> int:
    score = 0
    for value in record.values():
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            score += 1
        elif isinstance(value, (list, dict)) and value:
            score += 1
        elif not isinstance(value, (str, list, dict)):
            score += 1
    return score


def keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for keyword in keywords:
        key = keyword.lower()
        escaped = re.escape(key)
        escaped = escaped.replace(r"\ ", r"\s+")
        if re.fullmatch(r"[a-z][a-z0-9-]{2,}", key) and not key.endswith("s"):
            escaped = escaped + r"s?"
        pattern = escaped
        if key[:1].isalnum():
            pattern = r"(?<![a-z0-9])" + pattern
        if key[-1:].isalnum():
            pattern = pattern + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            hits.append(keyword)
    return hits


def safe_text_join(parts: Iterable[Any]) -> str:
    values = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            values.extend(str(item) for item in part if item)
        else:
            values.append(str(part))
    return normalize_whitespace(" ".join(values))


def load_watchlist(path: str | Path) -> dict[str, Any]:
    data = load_yaml_file(path) or {}
    journals = data.get("journals", [])
    by_id = {journal["id"]: journal for journal in journals if "id" in journal}
    by_name = {journal["journal_name"]: journal for journal in journals if "journal_name" in journal}
    data["by_id"] = by_id
    data["by_name"] = by_name
    return data
