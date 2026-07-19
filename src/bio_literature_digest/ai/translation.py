from __future__ import annotations

import json
import sys
from typing import Any

from .batching import chunk_by_limits
from .client import OpenAICompatibleChatClient, build_chat_client, resolve_chat_config, select_available_model_candidates
from .redaction import redact_record
from .schemas import BatchRecord, TranslationResult


TRANSLATION_SYSTEM_PROMPT = (
    "你是生物文献翻译助手。"
    "你将一次处理多篇文章；只返回 JSON 数组，不要附加解释，也不要输出推理过程。"
    "每个元素必须包含 id、title_zh、summary_zh、confidence。"
    "title_zh 要准确、简洁、自然；summary_zh 要根据对应文章的标题和摘要，用 1-3 句中文说明研究对象、主要发现或方法及生物学意义。"
    "不得编造输入中没有的结果，不得把不同文章的信息混在一起。"
    "必须为每个输入 id 返回且只返回一个对象，id 必须原样保留，不能遗漏、重复、改写或新增 id。"
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
    return (
        f"请处理以下 {len(batch)} 篇文章。每篇文章独立翻译和概括，返回恰好 {len(batch)} 个 JSON 对象。\n"
        "把输入中的 id 当作唯一关联键，完成后按 id 分配回原文章；不要使用数组下标代替 id。\n"
        "输入：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


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


def _validate_translation_results(batch: list[BatchRecord], results: list[TranslationResult]) -> dict[str, TranslationResult]:
    expected_ids = [item.id for item in batch]
    actual_ids = [item.id for item in results]
    if len(results) != len(batch):
        raise ValueError(f"Translation response count mismatch: expected={len(batch)} actual={len(results)}")
    if len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != set(expected_ids):
        raise ValueError("Translation response ids do not exactly match the input batch")
    by_id = {item.id: item for item in results}
    for item in batch:
        result = by_id[item.id]
        if not result.title_zh:
            raise ValueError(f"Translation response missing title_zh for record id={item.id}")
        if item.abstract and not result.summary_zh:
            raise ValueError(f"Translation response missing summary_zh for record id={item.id}")
    return by_id


def build_translation_client(ai_config: dict[str, Any]) -> OpenAICompatibleChatClient:
    """Build a chat client for translation."""

    return build_chat_client(ai_config)


def _translate_batch_with_model_fallback(
    client: OpenAICompatibleChatClient,
    batch: list[BatchRecord],
    ai_config: dict[str, Any],
    model_candidates: list[str],
    active_model_index: int,
) -> tuple[list[dict[str, str]], int]:
    attempt_order = model_candidates[active_model_index:] + model_candidates[:active_model_index]
    last_error: Exception | None = None
    for model in attempt_order:
        client.model = model
        try:
            payload = client.chat_json(
                [
                    {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                    {"role": "user", "content": _build_translation_user_prompt(batch)},
                ],
                temperature=float(ai_config.get("temperature", 0.0)),
                max_tokens=int(ai_config.get("max_output_tokens", 4096)),
            )
            results = _parse_translation_items(payload)
            by_id = _validate_translation_results(batch, results)
            translated: list[dict[str, str]] = []
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
            return translated, model_candidates.index(model)
        except Exception as error:  # noqa: BLE001
            last_error = error
            print(
                f"[ai] translation model failed; model={model} batch_size={len(batch)} "
                f"error={error.__class__.__name__}: {str(error)[:160]}",
                file=sys.stderr,
            )
    if last_error is not None:
        raise RuntimeError(f"All AI translation models failed for batch_size={len(batch)}") from last_error
    raise RuntimeError("No AI translation model was attempted")


def translate_records_with_nvidia(records: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, str]]:
    ai_config = resolve_chat_config(config)
    client = build_translation_client(ai_config)
    model_candidates = select_available_model_candidates(client, ai_config, default_ping=bool(ai_config.get("model_candidates") or ai_config.get("models")))

    translated: list[dict[str, str]] = []
    active_model_index = 0
    batches = build_translation_batches(records, config)
    original_max_retries = getattr(client, "max_retries", None)
    if original_max_retries is not None:
        configured_retries = int(ai_config.get("translation_max_retries", 1))
        client.max_retries = max(0, min(int(original_max_retries), configured_retries))
    try:
        for batch in batches:
            batch_translations, active_model_index = _translate_batch_with_model_fallback(
                client,
                batch,
                ai_config,
                model_candidates,
                active_model_index,
            )
            translated.extend(batch_translations)
    finally:
        if original_max_retries is not None:
            client.max_retries = original_max_retries
    return translated
