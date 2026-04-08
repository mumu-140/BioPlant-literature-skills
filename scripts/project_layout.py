#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from common import load_yaml_file
except ModuleNotFoundError:
    from scripts.common import load_yaml_file


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSETS_DIR = SKILL_DIR / "assets"
CONFIG_DIR = SKILL_DIR / "config"
CONTENT_CONFIG_DIR = CONFIG_DIR / "content"
INTEGRATIONS_CONFIG_DIR = CONFIG_DIR / "integrations"
RUNTIME_CONFIG_DIR = CONFIG_DIR / "runtime"
DOCS_DIR = SKILL_DIR / "docs"
OPS_DIR = SKILL_DIR / "ops"

DEFAULT_RUNTIME_CONFIG_PATH = RUNTIME_CONFIG_DIR / "production.local.yaml"


def canonical_paths() -> dict[str, Path]:
    return {
        "watchlist": CONTENT_CONFIG_DIR / "journal_watchlist.yaml",
        "rules": CONTENT_CONFIG_DIR / "category_rules.yaml",
        "glossary": CONTENT_CONFIG_DIR / "bio_translation_glossary.yaml",
        "terminology_sources": CONTENT_CONFIG_DIR / "terminology_sources.yaml",
        "email_config_example": INTEGRATIONS_CONFIG_DIR / "email_config.example.yaml",
        "email_config_local": INTEGRATIONS_CONFIG_DIR / "email_config.local.yaml",
        "users_config_example": INTEGRATIONS_CONFIG_DIR / "users.example.yaml",
        "users_config_local": INTEGRATIONS_CONFIG_DIR / "users.local.yaml",
        "email_style_example": INTEGRATIONS_CONFIG_DIR / "email_style.example.yaml",
        "email_style_local": INTEGRATIONS_CONFIG_DIR / "email_style.local.yaml",
        "translation_config_example": INTEGRATIONS_CONFIG_DIR / "translation_config.example.yaml",
        "translation_google_example": INTEGRATIONS_CONFIG_DIR / "translation_google_basic_v2.example.yaml",
        "translation_google_local": INTEGRATIONS_CONFIG_DIR / "translation_google_basic_v2.local.yaml",
        "translation_tencent_example": INTEGRATIONS_CONFIG_DIR / "translation_tencent_tmt.example.yaml",
        "translation_tencent_local": INTEGRATIONS_CONFIG_DIR / "translation_tencent_tmt.local.yaml",
        "llm_review_config_example": INTEGRATIONS_CONFIG_DIR / "llm_review_config.example.yaml",
        "email_template": ASSETS_DIR / "email_template.html",
        "user_quickstart": DOCS_DIR / "user_quickstart.md",
        "daily_artifact_contract": DOCS_DIR / "daily_artifact_contract.md",
        "launchd_readme": OPS_DIR / "launchd" / "README.md",
        "launchd_plist": OPS_DIR / "launchd" / "bio-digest-daily.plist",
        "launchd_plist_template": OPS_DIR / "launchd" / "bio-digest-daily.plist.template",
    }

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_runtime_config() -> dict[str, Any]:
    paths = canonical_paths()
    return {
        "environment": {
            "env_file": "${SKILL_DIR}/.env.local",
        },
        "paths": {
            "work_dir": "/private/tmp/bio-literature-digest",
            "archive_dir": "${SKILL_DIR}/archives/daily-digests",
            "review_workspace_dir": "${SKILL_DIR}/reviews/daily-reviews",
            "backlog_dir": "${SKILL_DIR}/reviews/backlog",
            "watchlist": str(paths["watchlist"]),
            "rules": str(paths["rules"]),
            "email_config": str(paths["email_config_local"]),
            "users_config": str(paths["users_config_local"]),
            "style_config": str(paths["email_style_local"]),
            "template": str(paths["email_template"]),
            "summary_config": str(paths["translation_google_local"]),
        },
        "delivery": {
            "smtp_profile": "primary_smtp",
            "timezone": "Asia/Shanghai",
            "delivery_time": "08:00",
            "allow_review_pending": True,
        },
        "providers": {
            "review_provider": "placeholder",
            "summary_provider": "google-basic-v2",
        },
        "web": {
            "base_url": "",
            "sync_enabled": False,
            "project_root": "${SKILL_DIR}/../bio-literature-digest-web",
        },
        "database": {
            "enabled": False,
            "sqlite_path": "${SKILL_DIR}/bio-literature-config/data/shared/bio_digest.sqlite3",
        },
        "scheduler": {
            "launchd": {
                "label": "org.example.bio-digest-daily",
                "wrapper_script": "${SKILL_DIR}/scripts/run_production_digest_launchd.sh",
                "working_directory": "${SKILL_DIR}",
                "stdout_log": "${SKILL_DIR}/logs/launchd/bio-digest-daily.stdout.log",
                "stderr_log": "${SKILL_DIR}/logs/launchd/bio-digest-daily.stderr.log",
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


def load_runtime_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path).resolve() if path else DEFAULT_RUNTIME_CONFIG_PATH
    merged = default_runtime_config()
    if config_path.exists():
        loaded = load_yaml_file(config_path) or {}
        if isinstance(loaded, dict):
            merged = deep_merge(merged, loaded)
    merged["runtime_config_path"] = str(config_path)
    return expand_config_value(merged)
