#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from scripts._bootstrap import canonical_paths, expand_config_value  # noqa: E402
except ModuleNotFoundError:
    from _bootstrap import canonical_paths, expand_config_value  # noqa: E402
try:
    from scripts.common import load_yaml_file
except ModuleNotFoundError:
    from common import load_yaml_file
try:
    from scripts.with_env import load_env_file
except ModuleNotFoundError:
    from with_env import load_env_file

from bio_literature_digest.ai.client import (  # noqa: E402
    OpenAICompatibleChatClient,
    normalize_model_candidates,
    resolve_chat_config,
)


CANONICAL_PATHS = canonical_paths()


def parse_models(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def load_chat_config(path: Path) -> dict[str, Any]:
    payload = load_yaml_file(path) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"AI config must be a mapping: {path}")
    ai_config = resolve_chat_config(payload)
    if not ai_config:
        raise SystemExit(f"AI config missing ai_chat/openai_compatible/nvidia_chat section: {path}")
    return ai_config


def build_client(ai_config: dict[str, Any]) -> OpenAICompatibleChatClient:
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
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping OpenAI-compatible AI model candidates with a pong probe.")
    parser.add_argument("--config", default=str(CANONICAL_PATHS["nvidia_ai_config_local"]))
    parser.add_argument("--env-file", default=str(CANONICAL_PATHS["env_file_local"]))
    parser.add_argument("--models", help="Comma-separated model candidates in priority order")
    parser.add_argument("--prompt", default="Reply with exactly: pong")
    parser.add_argument("--expected", default="pong")
    parser.add_argument("--max-tokens", type=int, default=8)
    args = parser.parse_args()

    config_path = Path(str(expand_config_value(args.config))).resolve()
    env_file = Path(str(expand_config_value(args.env_file))).resolve()
    load_env_file(env_file)
    ai_config = load_chat_config(config_path)
    configured_candidates = args.models or ai_config.get("model_candidates") or ai_config.get("models") or ""
    model_candidates = parse_models(configured_candidates) if isinstance(configured_candidates, str) else configured_candidates
    candidates = normalize_model_candidates(str(ai_config.get("model", "")), model_candidates)
    if not candidates:
        raise SystemExit("No model candidates configured.")

    client = build_client(ai_config)
    try:
        selected = client.select_model(
            candidates,
            prompt=args.prompt,
            expected=args.expected,
            max_tokens=args.max_tokens,
        )
    except Exception as error:
        print("ai_model_ping_ok=False")
        print(f"error={error.__class__.__name__}: {error}")
        print("tested_models=" + ",".join(candidates))
        return 1

    print("ai_model_ping_ok=True")
    print(f"selected_model={selected}")
    print("tested_models=" + ",".join(candidates[: candidates.index(selected) + 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
