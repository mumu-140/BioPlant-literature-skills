"""AI helper utilities for optional screening and translation backends."""

from .batching import chunk_by_limits
from .client import OpenAICompatibleChatClient, NvidiaChatClient, parse_json_content, resolve_api_key
from .redaction import redact_record, redact_text
from .screening import build_screening_batches, is_uncertain_review_candidate, review_records_with_nvidia
from .translation import build_translation_batches, translate_records_with_nvidia

__all__ = [
    "OpenAICompatibleChatClient",
    "NvidiaChatClient",
    "build_screening_batches",
    "build_translation_batches",
    "chunk_by_limits",
    "is_uncertain_review_candidate",
    "parse_json_content",
    "redact_record",
    "redact_text",
    "resolve_api_key",
    "review_records_with_nvidia",
    "translate_records_with_nvidia",
]
