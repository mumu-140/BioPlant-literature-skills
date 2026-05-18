from __future__ import annotations

import json
from typing import Any

from .batching import chunk_by_limits
from .client import OpenAICompatibleChatClient, resolve_chat_config
from .redaction import redact_record
from .schemas import BatchRecord, ReviewResult


SCREENING_SYSTEM_PROMPT = (
    "你是生物文献筛选助手。"
    "只返回 JSON 数组，不要附加解释。"
    "每个元素必须包含 id、decision、confidence、reason，可选 category_override。"
    "decision 只能是 keep、review、reject。"
    "仅根据给定条目和规则线索判断，不要扩展到输入之外的信息。"
)


def is_uncertain_review_candidate(record: dict[str, Any]) -> bool:
    reason = str(record.get("relevance_reason", "") or "").lower()
    status = str(record.get("relevance_status", "") or "").lower()
    category = str(record.get("category", "") or "").lower()
    if status != "keep":
        return False
    explicit_review_flag = record.get("relevance_review_needed")
    if isinstance(explicit_review_flag, bool):
        return explicit_review_flag
    if reason.startswith("kept by default source scope"):
        return True
    if "conditional journal" in reason or "strict bio source without biology-specific keyword match" in reason:
        return True
    if "matched keep keywords" in reason and category == "other":
        return True
    if "matched keep keywords" not in reason and "matched ai keep keywords" not in reason:
        return True
    return False


def build_screening_batches(records: list[dict[str, Any]], config: dict[str, Any]) -> list[list[BatchRecord]]:
    ai_config = resolve_chat_config(config)
    max_items = int(ai_config.get("max_batch_items", 12))
    max_chars = int(ai_config.get("max_batch_chars", 14_000))
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


def _build_screening_user_prompt(batch: list[BatchRecord]) -> str:
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
                "relevance_reason": item.relevance_reason,
            }
        )
    return "请判断以下条目是否保留、复核或排除，返回 JSON 数组：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_review_items(payload: Any) -> list[ReviewResult]:
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("reviews") or payload.get("data") or []
    else:
        items = payload
    if not isinstance(items, list):
        raise ValueError("AI review response must be a JSON array or contain an items array")

    results: list[ReviewResult] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Review item must be an object")
        results.append(
            ReviewResult(
                id=str(item.get("id", "")).strip(),
                decision=str(item.get("decision", "review")).strip().lower(),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                reason=str(item.get("reason", "")).strip(),
                category_override=(str(item.get("category_override", "")).strip() or None),
            )
        )
    return results


def review_records_with_nvidia(records: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    ai_config = resolve_chat_config(config)
    client = OpenAICompatibleChatClient(
        base_url=str(ai_config.get("base_url", "http://127.0.0.1:20128/v1")),
        model=str(ai_config.get("model", "")),
        api_key=str(ai_config.get("api_key", "")),
        api_key_envs=ai_config.get("api_key_envs") or ai_config.get("api_key_env") or ["AI_API_KEY", "OPENAI_API_KEY", "NGC_API_KEY", "NVIDIA_API_KEY"],
        timeout_seconds=int(ai_config.get("timeout_seconds", 60)),
        max_retries=int(ai_config.get("max_retries", 3)),
        retry_backoff_seconds=float(ai_config.get("retry_backoff_seconds", 0.8)),
    )

    reviewed: list[dict[str, Any]] = []
    batches = build_screening_batches(records, config)
    for batch in batches:
        payload = client.chat_json(
            [
                {"role": "system", "content": SCREENING_SYSTEM_PROMPT},
                {"role": "user", "content": _build_screening_user_prompt(batch)},
            ],
            temperature=float(ai_config.get("temperature", 0.0)),
            max_tokens=int(ai_config.get("max_output_tokens", 2048)),
        )
        results = _parse_review_items(payload)
        by_id = {item.id: item for item in results if item.id}
        for item in batch:
            result = by_id.get(item.id)
            if result is None:
                raise ValueError(f"Review response missing record id={item.id}")
            reviewed.append(
                {
                    "id": item.id,
                    "decision": result.decision,
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "category_override": result.category_override,
                }
            )
    return reviewed
