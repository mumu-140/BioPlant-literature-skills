from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BatchRecord:
    """Minimal AI payload record with a stable batch-local identifier."""

    id: str
    title_en: str
    abstract: str
    journal: str
    publication_stage: str
    category: str
    source_id: str = ""
    relevance_reason: str = ""
    tags: tuple[str, ...] = ()

    def prompt_size(self) -> int:
        return len(self.title_en) + len(self.abstract) + len(self.journal) + len(self.category) + len(self.relevance_reason)


@dataclass(frozen=True)
class TranslationResult:
    """Structured translation output returned by the AI layer."""

    id: str
    title_zh: str
    summary_zh: str
    confidence: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class ReviewResult:
    """Structured screening output returned by the AI layer."""

    id: str
    decision: str
    confidence: float
    reason: str
    category_override: str | None = None


def coerce_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()

