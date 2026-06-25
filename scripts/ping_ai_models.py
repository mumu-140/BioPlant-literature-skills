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
    build_chat_client,
    normalize_model_candidates,
    resolve_chat_config,
    select_available_model_candidates,
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
    return build_chat_client(ai_config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping OpenAI-compatible AI model candidates with a pong probe.")
    parser.add_argument("--config", default=str(CANONICAL_PATHS["nvidia_ai_config_local"]))
    parser.add_argument("--env-file", default=str(CANONICAL_PATHS["env_file_local"]))
    parser.add_argument("--models", help="Comma-separated model candidates in priority order")
    parser.add_argument("--prompt", default="Reply with exactly: pong")
    parser.add_argument("--expected", default="pong")
    parser.add_argument("--max-tokens", type=int)
    args = parser.parse_args()

    config_path = Path(str(expand_config_value(args.config))).resolve()
    env_file = Path(str(expand_config_value(args.env_file))).resolve()
    load_env_file(env_file)
    ai_config = load_chat_config(config_path)
    pong_config = ai_config.get("pong_test", {})
    if not isinstance(pong_config, dict):
        pong_config = {}
    configured_candidates = args.models or ai_config.get("model_candidates") or ai_config.get("models") or ""
    model_candidates = parse_models(configured_candidates) if isinstance(configured_candidates, str) else configured_candidates
    candidates = normalize_model_candidates(str(ai_config.get("model", "")), model_candidates)
    if not candidates:
        raise SystemExit("No model candidates configured.")

    client = build_client(ai_config)
    probe_config = dict(ai_config)
    probe_pong_config = dict(pong_config)
    probe_pong_config["enabled"] = True
    probe_pong_config["prompt"] = args.prompt
    probe_pong_config["expected"] = args.expected
    probe_pong_config["max_tokens"] = args.max_tokens if args.max_tokens is not None else int(pong_config.get("max_tokens") or 8)
    probe_config["pong_test"] = probe_pong_config
    try:
        selected_candidates = select_available_model_candidates(client, probe_config, default_ping=True)
    except Exception as error:
        print("ai_model_ping_ok=False")
        print(f"error={error.__class__.__name__}: {error}")
        print("tested_models=" + ",".join(candidates))
        return 1

    selected = selected_candidates[0]
    print("ai_model_ping_ok=True")
    print(f"selected_model={selected}")
    print("tested_models=" + ",".join(candidates[: candidates.index(selected) + 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
