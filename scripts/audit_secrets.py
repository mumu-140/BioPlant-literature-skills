#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ALLOWED_SECRET_FILES = {SKILL_DIR / ".env.local"}
SCAN_EXTENSIONS = {".py", ".yaml", ".yml", ".toml", ".md", ".txt", ".sh", ".ps1", ".json"}
SECRET_ENV_KEYS = [
    "GOOGLE_TRANSLATE_API_KEY",
    "TENCENT_TMT_SECRET_ID",
    "TENCENT_TMT_SECRET_KEY",
    "QQ_MAIL_APP_PASSWORD",
]


def load_env_pairs(env_path: Path) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if not env_path.exists():
        return pairs
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in SECRET_ENV_KEYS and value:
            pairs[key] = value
    return pairs


def should_scan(path: Path) -> bool:
    if path.is_dir():
        return False
    if path.name.startswith(".env.local"):
        return True
    return path.suffix in SCAN_EXTENSIONS


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the skill for leaked secrets outside .env.local.")
    parser.add_argument("--root", default=str(SKILL_DIR))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    env_pairs = load_env_pairs(SKILL_DIR / ".env.local")
    issues: list[str] = []

    for path in root.rglob("*"):
        if not should_scan(path):
            continue
        if path in ALLOWED_SECRET_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for key, value in env_pairs.items():
            if value and value in text:
                issues.append(f"{path}: contains secret value for {key}")

    if issues:
        print("Secret audit failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Secret audit passed. Sensitive values exist only in .env.local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
