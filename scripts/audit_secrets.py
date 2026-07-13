#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


SCAN_EXTENSIONS = {".py", ".yaml", ".yml", ".toml", ".md", ".txt", ".sh", ".ps1", ".json"}
SECRET_ENV_KEYS = {
    "BIO_DIGEST_API_KEY",
    "GOOGLE_TRANSLATE_API_KEY",
    "LLM_REVIEW_API_KEY",
    "QQ_MAIL_APP_PASSWORD",
    "SMTP_APP_PASSWORD",
    "SMTP_BACKUP_APP_PASSWORD",
    "TENCENT_TMT_SECRET_ID",
    "TENCENT_TMT_SECRET_KEY",
    "TENCENT_TMT_SESSION_TOKEN",
}
SKIP_PARTS = {".archive", ".git", ".helloagents", ".venv", "__pycache__", "var"}
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
TOKEN_PATTERNS = {
    "Bio Digest token": re.compile(r"\bbdg_[A-Za-z0-9_-]{32,}\b"),
    "GitHub token": re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
}


def load_env_pairs(env_path: Path) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if not env_path.exists():
        return pairs
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in SECRET_ENV_KEYS and value.strip():
            pairs[key.strip()] = value.strip()
    return pairs


def should_scan(path: Path, root: Path, allowed_env_file: Path) -> bool:
    if path == allowed_env_file or path.is_dir():
        return False
    relative = path.relative_to(root)
    if any(part in SKIP_PARTS for part in relative.parts):
        return False
    if path.name.startswith(".env"):
        return True
    return path.suffix.lower() in SCAN_EXTENSIONS


def scan_file(path: Path, known_secrets: dict[str, str]) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    issues = [f"包含私钥：{path}" for _ in [0] if PRIVATE_KEY_PATTERN.search(text)]
    for key, value in known_secrets.items():
        if value in text:
            issues.append(f"包含 {key} 的真实值：{path}")
    for label, pattern in TOKEN_PATTERNS.items():
        if pattern.search(text):
            issues.append(f"包含疑似 {label}：{path}")
    return issues


def audit(root: Path) -> list[str]:
    root = root.resolve()
    allowed_env_file = root / "local" / ".env.local"
    issues: list[str] = []
    if (root / ".env.local").exists():
        issues.append(f"不允许使用旧版根目录密钥文件：{root / '.env.local'}")
    known_secrets = load_env_pairs(allowed_env_file)
    for path in root.rglob("*"):
        if should_scan(path, root, allowed_env_file):
            issues.extend(scan_file(path, known_secrets))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="检查项目中是否存在越界密钥或私钥。")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    issues = audit(Path(args.root))
    if issues:
        print("密钥检查失败：")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("密钥检查通过：未在允许范围外发现敏感值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
