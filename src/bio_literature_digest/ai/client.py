from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def resolve_api_key(api_key_envs: Any, *, api_key: str = "") -> tuple[str, str]:
    """Resolve the configured API key without hard-coding a provider name.

    Prefer an explicit key supplied by private local config, then fall back to
    the first populated environment variable in the configured order.
    """

    explicit_key = str(api_key or "").strip()
    if explicit_key:
        return explicit_key, "<config>"

    candidates: list[str] = []
    if isinstance(api_key_envs, str) and api_key_envs.strip():
        candidates = [api_key_envs.strip()]
    elif isinstance(api_key_envs, list):
        candidates = [str(item).strip() for item in api_key_envs if str(item).strip()]
    else:
        candidates = ["AI_API_KEY", "OPENAI_API_KEY", "NGC_API_KEY", "NVIDIA_API_KEY"]

    for env_name in candidates:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value, env_name
    raise ValueError(f"No AI API key found in config or environment variables: {', '.join(candidates)}")


def resolve_chat_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return the OpenAI-compatible chat config from new or legacy keys."""

    for key in ("ai_chat", "openai_compatible", "nvidia_chat", "nvidia"):
        value = config.get(key)
        if isinstance(value, dict):
            return value
    return {}


def parse_json_content(text: str) -> Any:
    """Parse model output that may be wrapped in markdown fences."""

    cleaned = JSON_FENCE_PATTERN.sub("", (text or "").strip()).strip()
    if not cleaned:
        raise ValueError("Empty JSON response content")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min([idx for idx in (cleaned.find("["), cleaned.find("{")) if idx != -1], default=-1)
        end = max(cleaned.rfind("]"), cleaned.rfind("}"))
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("OpenAI-compatible chat response missing choices")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "".join(parts).strip()
    text = choice.get("text") if isinstance(choice, dict) else ""
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise ValueError("OpenAI-compatible chat response missing assistant message content")


@dataclass
class OpenAICompatibleChatClient:
    """Minimal OpenAI-compatible chat client for any configured base URL/key."""

    base_url: str
    model: str
    api_key_envs: Any
    api_key: str = ""
    timeout_seconds: int = 60
    max_retries: int = 3
    retry_backoff_seconds: float = 0.8
    opener: Any = urlopen

    def __post_init__(self) -> None:
        self.api_key, self.api_key_env = resolve_api_key(self.api_key_envs, api_key=self.api_key)
        self.base_url = self.base_url.rstrip("/")

    @property
    def endpoint(self) -> str:
        return urljoin(f"{self.base_url}/", "chat/completions")

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                last_error = error
                if error.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise
            except URLError as error:
                last_error = error
                if attempt >= self.max_retries:
                    raise
            time.sleep(self.retry_backoff_seconds * (attempt + 1))

        if last_error is not None:
            raise last_error
        raise ValueError("OpenAI-compatible chat request failed without a captured error")

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None) -> Any:
        payload = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        content = extract_message_content(payload)
        return parse_json_content(content)


NvidiaChatClient = OpenAICompatibleChatClient

