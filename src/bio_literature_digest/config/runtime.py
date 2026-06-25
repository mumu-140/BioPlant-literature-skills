from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PACKAGE_ROOT.parent
SKILL_DIR = SRC_ROOT.parent
ASSETS_DIR = SKILL_DIR / "assets"
CONFIG_DIR = SKILL_DIR / "config"
CONTENT_CONFIG_DIR = CONFIG_DIR / "content"
INTEGRATIONS_CONFIG_DIR = CONFIG_DIR / "integrations"
RUNTIME_CONFIG_DIR = CONFIG_DIR / "runtime"
DOCS_DIR = SKILL_DIR / "docs"
OPS_DIR = SKILL_DIR / "ops"
LOCAL_DIR = SKILL_DIR / "local"
VAR_DIR = SKILL_DIR / "var"

PREFERRED_RUNTIME_CONFIG_PATH = LOCAL_DIR / "runtime" / "production.yaml"
DEFAULT_RUNTIME_CONFIG_PATH = PREFERRED_RUNTIME_CONFIG_PATH
RUNTIME_EXAMPLE_CONFIG_PATH = RUNTIME_CONFIG_DIR / "production.example.yaml"


def canonical_paths() -> dict[str, Path]:
    return {
        "skill_dir": SKILL_DIR,
        "src_root": SRC_ROOT,
        "local_dir": LOCAL_DIR,
        "var_dir": VAR_DIR,
        "watchlist": CONTENT_CONFIG_DIR / "journal_watchlist.yaml",
        "rules": CONTENT_CONFIG_DIR / "category_rules.yaml",
        "glossary": CONTENT_CONFIG_DIR / "bio_translation_glossary.yaml",
        "terminology_sources": CONTENT_CONFIG_DIR / "terminology_sources.yaml",
        "email_config_example": INTEGRATIONS_CONFIG_DIR / "email_config.example.yaml",
        "users_config_example": INTEGRATIONS_CONFIG_DIR / "users.example.yaml",
        "email_style_example": INTEGRATIONS_CONFIG_DIR / "email_style.example.yaml",
        "translation_config_example": INTEGRATIONS_CONFIG_DIR / "translation_config.example.yaml",
        "translation_tencent_example": INTEGRATIONS_CONFIG_DIR / "translation_tencent_tmt.example.yaml",
        "ai_chat_config_example": INTEGRATIONS_CONFIG_DIR / "ai_chat.example.yaml",
        "nvidia_ai_config_example": INTEGRATIONS_CONFIG_DIR / "ai_chat.example.yaml",  # compat alias
        "llm_review_config_example": INTEGRATIONS_CONFIG_DIR / "llm_review_config.example.yaml",
        "env_file_example": CONFIG_DIR / "env.local.example",
        "runtime_config_example": RUNTIME_EXAMPLE_CONFIG_PATH,
        "runtime_config_local": PREFERRED_RUNTIME_CONFIG_PATH,
        "env_file_local": LOCAL_DIR / ".env.local",
        "email_config_local": LOCAL_DIR / "integrations" / "email_config.yaml",
        "users_config_local": LOCAL_DIR / "integrations" / "users.yaml",
        "email_style_local": LOCAL_DIR / "integrations" / "email_style.yaml",
        "translation_tencent_local": LOCAL_DIR / "integrations" / "translation_tencent_tmt.yaml",
        "ai_chat_config_local": LOCAL_DIR / "integrations" / "nvidia_ai.yaml",
        "nvidia_ai_config_local": LOCAL_DIR / "integrations" / "nvidia_ai.yaml",  # compat alias
        "email_template": ASSETS_DIR / "email_template.html",
        "user_quickstart": DOCS_DIR / "user_quickstart.md",
        "daily_artifact_contract": DOCS_DIR / "daily_artifact_contract.md",
        "launchd_readme": OPS_DIR / "launchd" / "README.md",
        "launchd_plist": OPS_DIR / "launchd" / "bio-digest-daily.plist",
        "launchd_plist_template": OPS_DIR / "launchd" / "bio-digest-daily.plist.template",
        "imap_tool": OPS_DIR / "tools" / "download_imap_attachments.py",
    }


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def fallback_runtime_config() -> dict[str, Any]:
    paths = canonical_paths()
    return {
        "environment": {
            "env_file": "${SKILL_DIR}/local/.env.local",
        },
        "paths": {
            "work_dir": "${SKILL_DIR}/var/work/current",
            "archive_dir": "${SKILL_DIR}/var/archives/daily-digests",
            "review_workspace_dir": "${SKILL_DIR}/var/reviews/daily-reviews",
            "backlog_dir": "${SKILL_DIR}/var/reviews/backlog",
            "watchlist": str(paths["watchlist"]),
            "rules": str(paths["rules"]),
            "email_config": str(paths["email_config_local"]),
            "users_config": str(paths["users_config_local"]),
            "style_config": str(paths["email_style_local"]),
            "template": str(paths["email_template"]),
            "summary_config": str(paths["nvidia_ai_config_local"]),
        },
        "delivery": {
            "smtp_profile": "primary_smtp",
            "timezone": "Asia/Shanghai",
            "delivery_time": "08:00",
            "window_policy": "previous_day",
            "allow_review_pending": True,
        },
        "providers": {
            "review_provider": "placeholder",
            "summary_provider": "nvidia-chat",
        },
        "web": {
            "base_url": "",
            "sync_enabled": False,
            "project_root": "",
        },
        "database": {
            "enabled": False,
            "sqlite_path": "${SKILL_DIR}/var/db/bio_digest.sqlite3",
        },
        "scheduler": {
            "launchd": {
                "label": "org.example.bio-digest-daily",
                "wrapper_script": "${SKILL_DIR}/scripts/run_production_digest_launchd.sh",
                "working_directory": "${SKILL_DIR}",
                "stdout_log": "${SKILL_DIR}/var/logs/launchd/bio-digest-daily.stdout.log",
                "stderr_log": "${SKILL_DIR}/var/logs/launchd/bio-digest-daily.stderr.log",
            }
        },
    }


def expand_config_value(value: Any) -> Any:
    if isinstance(value, str):
        expanded = value.replace("${SKILL_DIR}", str(SKILL_DIR)).replace("${HOME}", str(Path.home()))
        expanded = os.path.expandvars(os.path.expanduser(expanded))
        return expanded
    if isinstance(value, dict):
        return {key: expand_config_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_config_value(item) for item in value]
    return value


def load_yaml_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _existing_override_candidates(explicit_path: str | Path | None = None) -> list[Path]:
    if explicit_path:
        return [Path(explicit_path).resolve()]
    return [PREFERRED_RUNTIME_CONFIG_PATH]


def _resolve_local_path(path: str | Path) -> str:
    path_obj = Path(str(path)).expanduser()
    return str(path_obj)


def load_runtime_config(path: str | Path | None = None) -> dict[str, Any]:
    merged = fallback_runtime_config()
    if RUNTIME_EXAMPLE_CONFIG_PATH.exists():
        example_data = load_yaml_file(RUNTIME_EXAMPLE_CONFIG_PATH) or {}
        if isinstance(example_data, dict):
            merged = deep_merge(merged, example_data)

    resolved_path = ""
    for candidate in _existing_override_candidates(path):
        if candidate.exists():
            override_data = load_yaml_file(candidate) or {}
            if isinstance(override_data, dict):
                merged = deep_merge(merged, override_data)
            resolved_path = str(candidate)
            break
        if path is not None:
            resolved_path = str(candidate)
            break
    if not resolved_path:
        resolved_path = str(PREFERRED_RUNTIME_CONFIG_PATH)

    expanded = expand_config_value(merged)
    if isinstance(expanded, dict):
        environment = expanded.get("environment", {})
        paths = expanded.get("paths", {})
        database = expanded.get("database", {})
        if isinstance(environment, dict) and environment.get("env_file"):
            environment["env_file"] = _resolve_local_path(environment["env_file"])
        if isinstance(paths, dict):
            for key in ("email_config", "users_config", "style_config", "summary_config"):
                if paths.get(key):
                    paths[key] = _resolve_local_path(paths[key])
        if isinstance(database, dict) and database.get("sqlite_path"):
            database["sqlite_path"] = str(Path(str(database["sqlite_path"])).expanduser())
        expanded["runtime_config_path"] = resolved_path
    return expanded
