#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SKILL_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bio_literature_digest.ai import (  # noqa: E402
    OpenAICompatibleChatClient,
    chunk_by_limits,
    normalize_model_candidates,
    parse_json_content,
    redact_text,
    resolve_api_key,
)
from bio_literature_digest.ai import translation as translation_module  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class AiChatHelpersTest(unittest.TestCase):
    def test_resolve_api_key_prefers_configured_environment_order(self) -> None:
        with mock.patch.dict(os.environ, {"AI_API_KEY": "direct-key", "OPENAI_API_KEY": "openai-key"}, clear=False):
            key, env_name = resolve_api_key(["AI_API_KEY", "OPENAI_API_KEY"])
        self.assertEqual(key, "direct-key")
        self.assertEqual(env_name, "AI_API_KEY")

    def test_resolve_api_key_prefers_explicit_private_config_key(self) -> None:
        key, source = resolve_api_key(["AI_API_KEY"], api_key="local-private-key")
        self.assertEqual(key, "local-private-key")
        self.assertEqual(source, "<config>")

    def test_redact_text_removes_secrets_urls_emails_and_paths(self) -> None:
        text = "Contact a@example.com with nvapi-secret123456 at https://example.com/a or /path/to/key.txt"
        redacted = redact_text(text)
        self.assertIn("[redacted-email]", redacted)
        self.assertIn("[redacted-url]", redacted)
        self.assertIn("[redacted-token]", redacted)
        self.assertIn("[redacted-path]", redacted)
        self.assertNotIn("a@example.com", redacted)

    def test_chunk_by_limits_preserves_order_and_splits_by_count(self) -> None:
        batches = chunk_by_limits(["a", "b", "c"], max_items=2, max_chars=99, size_fn=len)
        self.assertEqual(batches, [["a", "b"], ["c"]])

    def test_parse_json_content_accepts_markdown_fenced_arrays(self) -> None:
        payload = parse_json_content('```json\n[{"id": "1", "decision": "keep"}]\n```')
        self.assertEqual(payload[0]["decision"], "keep")

    def test_openai_compatible_chat_client_uses_configured_endpoint_and_key(self) -> None:
        captured = {}

        def fake_opener(request, timeout=0):  # type: ignore[override]
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["auth"] = request.get_header("Authorization")
            return FakeResponse({"choices": [{"message": {"content": "{\"ok\": true}"}}]})

        client = OpenAICompatibleChatClient(
            base_url="http://127.0.0.1:20128/v1",
            model="configured-model",
            api_key="configured-key",
            api_key_envs=["AI_API_KEY"],
            timeout_seconds=7,
            opener=fake_opener,
        )
        payload = client.chat_json([{"role": "user", "content": "hello"}])

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(captured["url"], "http://127.0.0.1:20128/v1/chat/completions")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["auth"], "Bearer configured-key")

    def test_normalize_model_candidates_keeps_priority_and_appends_configured_model(self) -> None:
        candidates = normalize_model_candidates("fallback-model", ["deepseek-4-pro", "glm-4"])
        self.assertEqual(candidates, ["deepseek-4-pro", "glm-4", "fallback-model"])

    def test_openai_compatible_chat_client_selects_first_model_that_pongs(self) -> None:
        seen_models: list[str] = []

        def fake_opener(request, timeout=0):  # type: ignore[override]
            payload = json.loads(request.data.decode("utf-8"))
            model = payload["model"]
            seen_models.append(model)
            content = "pong" if model == "glm-4" else "not available"
            return FakeResponse({"choices": [{"message": {"content": content}}]})

        client = OpenAICompatibleChatClient(
            base_url="http://127.0.0.1:20128/v1",
            model="minimax-chat",
            api_key="configured-key",
            api_key_envs=["AI_API_KEY"],
            max_retries=0,
            opener=fake_opener,
        )
        selected = client.select_model(["deepseek-4-pro", "glm-4"], max_tokens=4)

        self.assertEqual(selected, "glm-4")
        self.assertEqual(client.model, "glm-4")
        self.assertEqual(seen_models, ["deepseek-4-pro", "glm-4"])

    def test_openai_compatible_chat_client_retries_timeout_with_sleep_cap(self) -> None:
        calls = 0

        def fake_opener(request, timeout=0):  # type: ignore[override]
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError("timed out")
            return FakeResponse({"choices": [{"message": {"content": "{\"ok\": true}"}}]})

        client = OpenAICompatibleChatClient(
            base_url="http://127.0.0.1:20128/v1",
            model="configured-model",
            api_key="configured-key",
            api_key_envs=["AI_API_KEY"],
            max_retries=1,
            retry_backoff_seconds=99.0,
            retry_max_sleep_seconds=2.0,
            opener=fake_opener,
        )
        with mock.patch("bio_literature_digest.ai.client.time.sleep") as mocked_sleep:
            payload = client.chat_json([{"role": "user", "content": "hello"}])

        self.assertEqual(payload, {"ok": True})
        mocked_sleep.assert_called_once_with(2.0)
        self.assertEqual(calls, 2)

    def test_translation_switches_to_next_model_after_batch_failure(self) -> None:
        seen_models: list[str] = []

        class FakeClient:
            model = "bad-model"

            def pong(self, **kwargs):  # type: ignore[no-untyped-def]
                return True

            def chat_json(self, messages, *, temperature=0.0, max_tokens=None):  # type: ignore[no-untyped-def]
                seen_models.append(self.model)
                if self.model == "bad-model":
                    raise TimeoutError("batch timed out")
                return [{"id": "1", "title_zh": "中文标题", "summary_zh": "中文摘要", "confidence": 0.9}]

        records = [{"title_en": "A plant method", "abstract": "A plant method abstract.", "journal": "Test"}]
        config = {
            "ai_chat": {
                "model": "bad-model",
                "model_candidates": ["bad-model", "good-model"],
                "pong_test": {"enabled": True},
                "max_retries": 0,
            }
        }
        with mock.patch.object(translation_module, "build_chat_client", return_value=FakeClient()):
            translated = translation_module.translate_records_with_nvidia(records, config)

        self.assertEqual(translated[0]["title_zh"], "中文标题")
        self.assertEqual(seen_models, ["bad-model", "good-model"])


if __name__ == "__main__":
    unittest.main()
