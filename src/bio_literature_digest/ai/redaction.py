from __future__ import annotations

import re
from typing import Any

EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
TOKEN_PATTERN = re.compile(
    r"\b(?:Bearer\s+)?(?:sk|rk|pk|nvapi|ngc|ghp|glpat|xoxb|xoxp|ya29\.[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+)[A-Za-z0-9._=-]{8,}\b"
)
LONG_HEX_PATTERN = re.compile(r"\b[a-f0-9]{32,}\b", re.IGNORECASE)
LOCAL_PATH_PATTERN = re.compile(r"(?:(?:[A-Za-z]:)?[/\\][^\s\"'<>]+)")


def redact_text(value: str) -> str:
    """Remove obvious secrets and machine-local paths from free text."""

    text = value or ""
    text = EMAIL_PATTERN.sub("[redacted-email]", text)
    text = URL_PATTERN.sub("[redacted-url]", text)
    text = TOKEN_PATTERN.sub("[redacted-token]", text)
    text = LONG_HEX_PATTERN.sub("[redacted-token]", text)
    text = LOCAL_PATH_PATTERN.sub("[redacted-path]", text)
    return re.sub(r"\s+", " ", text).strip()


def redact_record(record: dict[str, Any], *, allowed_keys: set[str] | None = None) -> dict[str, Any]:
    """Return a minimal, redacted copy of a record for AI prompts."""

    keys = allowed_keys or {
        "id",
        "source_id",
        "journal",
        "publication_stage",
        "category",
        "title_en",
        "abstract",
        "tags",
        "relevance_reason",
        "relevance_review_needed",
    }
    output: dict[str, Any] = {}
    for key in keys:
        if key not in record:
            continue
        value = record[key]
        if isinstance(value, str):
            output[key] = redact_text(value)
        elif isinstance(value, list):
            output[key] = [redact_text(str(item)) for item in value if item is not None and str(item).strip()]
        else:
            output[key] = value
    return output
