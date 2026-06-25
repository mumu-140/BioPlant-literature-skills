from __future__ import annotations

import json
from typing import Any

from .batching import chunk_by_limits
from .client import OpenAICompatibleChatClient, resolve_chat_config
from .redaction import redact_record
from .schemas import BatchRecord, TranslationResult


TRANSLATION_SYSTEM_PROMPT = (
    "你是生物文献翻译助手。"
    "只返回 JSON 数组，不要附加解释。"
    "每个元素必须包含 id、title_zh、summary_zh、confidence。"
    "title_zh 要自然准确，summary_zh 要用简洁中文概括标题和摘要，保持学术表达。"
    "输出顺序必须与输入一致。"
)


def build_translation_batches(records: list[dict[str, Any]], config: dict[str, Any]) -> list[list[BatchRecord]]:
    ai_config = resolve_chat_config(config)
    max_items = int(ai_config.get("max_batch_items", 8))
    max_chars = int(ai_config.get("max_batch_chars", 12_000))
    batch_records: list[BatchRecord] = []
    for index, record in enumerate(records, start=1):
        sanitized = redact_record(record)
        batch_records.append(
            BatchRecord(
                id=str(index),
                title_en=str(sanitized.get("title_en", "") or record.get("title_en", "") or ""),
                abstract=str(sanitized.get("abstract", "") or record.get("abstract", "") or ""),
                journal=str(sanitized.get("journal", "") or record.get("journal", "") or ""),
                publication_stage=str(sanitized.get("publication_stage", "") or record.get("publication_stage", "") or ""),
                category=str(sanitized.get("category", "") or record.get("category", "") or ""),
                source_id=str(sanitized.get("source_id", "") or record.get("source_id", "") or ""),
                relevance_reason=str(sanitized.get("relevance_reason", "") or record.get("relevance_reason", "") or ""),
                tags=tuple(str(tag) for tag in sanitized.get("tags", []) if str(tag).strip()),
            )
        )
    return chunk_by_limits(batch_records, max_items=max_items, max_chars=max_chars, size_fn=lambda item: item.prompt_size())


def _build_translation_user_prompt(batch: list[BatchRecord]) -> str:
    payload = []
    for item in batch:
        payload.append(
            {
                "id": item.id,
                "title_en": item.title_en,
                "abstract": item.abstract,
                "journal": item.journal,
                "publication_stage": item.publication_stage,
                "category": item.category,
                "source_id": item.source_id,
            }
        )
    return "请翻译并概括以下条目，返回 JSON 数组：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_translation_items(payload: Any) -> list[TranslationResult]:
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("translations") or payload.get("data") or []
    else:
        items = payload
    if not isinstance(items, list):
        raise ValueError("AI translation response must be a JSON array or contain an items array")

    results: list[TranslationResult] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Translation item must be an object")
        results.append(
            TranslationResult(
                id=str(item.get("id", "")).strip(),
                title_zh=str(item.get("title_zh", "")).strip(),
                summary_zh=str(item.get("summary_zh", "")).strip(),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                notes=str(item.get("notes", "")).strip(),
            )
        )
    return results


def _bool_config(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_translation_client(ai_config: dict[str, Any]) -> OpenAICompatibleChatClient:
    """Build a chat client and optionally select an available model by pong test."""

    client = OpenAICompatibleChatClient(
        base_url=str(ai_config.get("base_url", "http://127.0.0.1:20128/v1")),
        model=str(ai_config.get("model", "")),
        api_key=str(ai_config.get("api_key", "")),
        api_key_envs=ai_config.get("api_key_envs") or ai_config.get("api_key_env") or ["AI_API_KEY", "OPENAI_API_KEY", "NGC_API_KEY", "NVIDIA_API_KEY"],
        timeout_seconds=int(ai_config.get("timeout_seconds", 60)),
        max_retries=int(ai_config.get("max_retries", 3)),
        retry_backoff_seconds=float(ai_config.get("retry_backoff_seconds", 0.8)),
    )

    pong_config = ai_config.get("pong_test", {})
    if not isinstance(pong_config, dict):
        pong_config = {}
    model_candidates = ai_config.get("model_candidates") or ai_config.get("models")
    if _bool_config(pong_config.get("enabled"), default=bool(model_candidates)):
        selected_model = client.select_model(
            model_candidates or [client.model],
            prompt=str(pong_config.get("prompt") or "Reply with exactly: pong"),
            expected=str(pong_config.get("expected") or "pong"),
            max_tokens=int(pong_config.get("max_tokens") or 8),
        )
        print(f"[ai] selected model via pong: {selected_model}")
    return client


def translate_records_with_nvidia(records: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, str]]:
    ai_config = resolve_chat_config(config)
    client = build_translation_client(ai_config)

    translated: list[dict[str, str]] = []
    batches = build_translation_batches(records, config)
    for batch in batches:
        payload = client.chat_json(
            [
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": _build_translation_user_prompt(batch)},
            ],
            temperature=float(ai_config.get("temperature", 0.0)),
            max_tokens=int(ai_config.get("max_output_tokens", 4096)),
        )
        results = _parse_translation_items(payload)
        by_id = {item.id: item for item in results if item.id}
        for item in batch:
            result = by_id.get(item.id)
            if result is None:
                raise ValueError(f"Translation response missing record id={item.id}")
            translated.append(
                {
                    "id": item.id,
                    "title_zh": result.title_zh or item.title_en,
                    "summary_zh": result.summary_zh,
                }
            )
    return translated
