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
    parse_json_content,
    redact_text,
    resolve_api_key,
)


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


if __name__ == "__main__":
    unittest.main()
