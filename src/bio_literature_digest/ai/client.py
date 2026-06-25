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


def normalize_model_candidates(model: str, model_candidates: Any) -> list[str]:
    """Return candidate model names in configured priority order."""

    candidates: list[str] = []
    if isinstance(model_candidates, str) and model_candidates.strip():
        candidates = [model_candidates.strip()]
    elif isinstance(model_candidates, list):
        candidates = [str(item).strip() for item in model_candidates if str(item).strip()]

    configured_model = str(model or "").strip()
    if configured_model and configured_model not in candidates:
        candidates.append(configured_model)
    return candidates


def bool_config(value: Any, *, default: bool = False) -> bool:
    """Read common YAML/env-style boolean values."""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_chat_client(ai_config: dict[str, Any]) -> "OpenAICompatibleChatClient":
    """Build a configured OpenAI-compatible chat client."""

    return OpenAICompatibleChatClient(
        base_url=str(ai_config.get("base_url", "http://127.0.0.1:20128/v1")),
        model=str(ai_config.get("model", "")),
        api_key=str(ai_config.get("api_key", "")),
        api_key_envs=ai_config.get("api_key_envs")
        or ai_config.get("api_key_env")
        or ["AI_API_KEY", "OPENAI_API_KEY", "NGC_API_KEY", "NVIDIA_API_KEY"],
        timeout_seconds=int(ai_config.get("timeout_seconds", 60)),
        max_retries=int(ai_config.get("max_retries", 3)),
        retry_backoff_seconds=float(ai_config.get("retry_backoff_seconds", 0.8)),
        retry_max_sleep_seconds=float(ai_config.get("retry_max_sleep_seconds", 20.0)),
    )


def select_available_model_candidates(
    client: "OpenAICompatibleChatClient",
    ai_config: dict[str, Any],
    *,
    default_ping: bool = False,
) -> list[str]:
    """Return model candidates that should be tried for real work."""

    model_candidates = ai_config.get("model_candidates") or ai_config.get("models")
    candidates = normalize_model_candidates(client.model, model_candidates)
    if not candidates:
        raise ValueError("No AI model candidates configured")

    pong_config = ai_config.get("pong_test", {})
    if not isinstance(pong_config, dict):
        pong_config = {}
    if not bool_config(pong_config.get("enabled"), default=default_ping):
        return candidates

    prompt = str(pong_config.get("prompt") or "Reply with exactly: pong")
    expected = str(pong_config.get("expected") or "pong")
    max_tokens = int(pong_config.get("max_tokens") or 8)
    original_model = client.model
    errors: list[str] = []
    for index, model in enumerate(candidates):
        client.model = model
        try:
            if client.pong(prompt=prompt, expected=expected, max_tokens=max_tokens):
                print(f"[ai] model pong ok: {model}")
                return [model] + candidates[index + 1 :] + candidates[:index]
            else:
                errors.append(f"{model}: response did not contain {expected!r}")
        except Exception as error:  # noqa: BLE001
            errors.append(f"{model}: {error.__class__.__name__}: {str(error)[:160]}")
    client.model = original_model
    raise ValueError("No AI model passed pong test. " + "; ".join(errors))


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


def extract_reasoning_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    if isinstance(message, dict) and isinstance(message.get("reasoning_content"), str):
        return message["reasoning_content"].strip()
    return ""


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
    retry_max_sleep_seconds: float = 20.0
    opener: Any = urlopen

    def __post_init__(self) -> None:
        self.api_key, self.api_key_env = resolve_api_key(self.api_key_envs, api_key=self.api_key)
        self.base_url = self.base_url.rstrip("/")

    @property
    def endpoint(self) -> str:
        return urljoin(f"{self.base_url}/", "chat/completions")

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None) -> dict[str, Any]:
        if not self.model.strip():
            raise ValueError("No AI model configured")
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
            except (OSError, TimeoutError) as error:
                last_error = error
                if attempt >= self.max_retries:
                    raise
            sleep_seconds = min(self.retry_max_sleep_seconds, self.retry_backoff_seconds * (attempt + 1))
            time.sleep(sleep_seconds)

        if last_error is not None:
            raise last_error
        raise ValueError("OpenAI-compatible chat request failed without a captured error")

    def chat_text(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Return assistant text content from a chat completion."""

        payload = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return extract_message_content(payload)

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None) -> Any:
        return parse_json_content(self.chat_text(messages, temperature=temperature, max_tokens=max_tokens))

    def pong(
        self,
        *,
        prompt: str = "Reply with exactly: pong",
        expected: str = "pong",
        max_tokens: int = 8,
    ) -> bool:
        """Probe the configured model with a tiny deterministic response test."""

        payload = self.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        try:
            content = extract_message_content(payload)
        except ValueError:
            content = extract_reasoning_content(payload)
        return expected.strip().lower() in content.strip().lower()

    def select_model(
        self,
        model_candidates: Any,
        *,
        prompt: str = "Reply with exactly: pong",
        expected: str = "pong",
        max_tokens: int = 8,
    ) -> str:
        """Select the first candidate model that passes the pong test."""

        original_model = self.model
        candidates = normalize_model_candidates(original_model, model_candidates)
        if not candidates:
            raise ValueError("No AI model candidates configured")

        errors: list[str] = []
        for model in candidates:
            self.model = model
            try:
                if self.pong(prompt=prompt, expected=expected, max_tokens=max_tokens):
                    return model
                errors.append(f"{model}: response did not contain {expected!r}")
            except Exception as error:
                errors.append(f"{model}: {error.__class__.__name__}: {str(error)[:160]}")
        self.model = original_model
        raise ValueError("No AI model passed pong test. " + "; ".join(errors))


NvidiaChatClient = OpenAICompatibleChatClient
