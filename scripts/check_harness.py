#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

try:
    from project_layout import SKILL_DIR
except ModuleNotFoundError:
    from scripts.project_layout import SKILL_DIR


IGNORED_DIR_NAMES = {".venv", "__pycache__", "archives", "reviews", "logs", ".git"}
IGNORED_FILE_NAMES = {".DS_Store", ".env.local"}
IGNORED_SUFFIXES = {".pyc"}
LOCAL_CONFIG_SUFFIX = ".local.yaml"
ALLOWED_DOC_PATH_MARKERS = {"/path/to/", "/private/tmp/bio-literature-digest", "org.example", "example.com"}

PRIVATE_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@(?!(?:example\.com|example\.org|test\.invalid)\b)[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
ABSOLUTE_USER_PATH_RE = re.compile(r"(/Users/[^/\s]+|/home/[^/\s]+|[A-Za-z]:\\\\Users\\\\[^\\\s]+)")
PERSONAL_HOST_RE = re.compile(r"\b(?:accept\.yangsen666\.cloud|yangsen666\.cloud)\b", re.I)
LEGACY_STRUCTURE_RE = re.compile(r"\breferences/")
PERSONAL_PROFILE_RE = re.compile(r"\bqq_mail\b")
PERSONAL_LABEL_RE = re.compile(r"\bcom\.mumu\.")
PERSONAL_SMTP_RE = re.compile(r"\bsmtp\.qq\.com\b", re.I)


def iter_project_files(project_root: Path) -> Iterable[Path]:
    for path in project_root.rglob("*"):
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        if path.is_dir():
            continue
        if path.name in IGNORED_FILE_NAMES:
            continue
        if path.suffix in IGNORED_SUFFIXES:
            continue
        yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def is_local_config(path: Path) -> bool:
    return path.name.endswith(LOCAL_CONFIG_SUFFIX)


def should_scan_for_sensitive_literals(path: Path) -> bool:
    if is_local_config(path):
        return False
    if path.suffix == ".plist":
        return False
    return True


def build_report(project_root: Path | None = None) -> tuple[list[str], list[str]]:
    root = (project_root or SKILL_DIR).resolve()
    docs_dir = root / "docs"
    ops_dir = root / "ops"
    issues: list[str] = []
    notes: list[str] = []

    expected_dirs = [
        root / "config" / "content",
        root / "config" / "integrations",
        root / "config" / "runtime",
        root / "scripts",
        root / "docs",
        root / "ops",
    ]
    for required_dir in expected_dirs:
        if not required_dir.exists():
            issues.append(f"缺少固定目录: {required_dir}")

    if (root / "references").exists():
        issues.append("残留旧目录 `references/`，应继续使用 config/docs/ops 分层")

    harness_doc = docs_dir / "engineering_harness.md"
    if not harness_doc.exists():
        issues.append(f"缺少 harness 文档: {harness_doc}")
    else:
        notes.append(f"harness 文档存在: {harness_doc}")

    launchd_dir = ops_dir / "launchd"
    tracked_plists = [path for path in launchd_dir.glob("*.plist") if path.name != ".DS_Store"]
    if tracked_plists:
        issues.extend(f"源码目录中存在生成型 plist，应删除并通过脚本生成: {path}" for path in tracked_plists)

    template_files = list(launchd_dir.glob("*.plist.template"))
    if not template_files:
        issues.append(f"缺少 launchd 模板文件: {launchd_dir}")

    for path in iter_project_files(root):
        text = read_text(path)
        if not text:
            continue

        relative = path.relative_to(root)
        if relative.as_posix() in {"scripts/check_harness.py", "scripts/check_alignment.py", "docs/engineering_harness.md"}:
            continue
        if LEGACY_STRUCTURE_RE.search(text):
            issues.append(f"{relative} 仍引用旧结构 `references/`")

        if not should_scan_for_sensitive_literals(path):
            continue

        if PRIVATE_EMAIL_RE.search(text):
            issues.append(f"{relative} 含真实邮箱，必须移到本地配置或示例占位")
        if ABSOLUTE_USER_PATH_RE.search(text):
            issues.append(f"{relative} 含个人路径，必须改成配置、模板变量或 /path/to 占位")
        if PERSONAL_HOST_RE.search(text):
            issues.append(f"{relative} 含个人域名，必须移到本地配置")
        if PERSONAL_LABEL_RE.search(text):
            issues.append(f"{relative} 含个人化 scheduler label，必须改为通用占位")
        if PERSONAL_SMTP_RE.search(text) and "email_config.local.yaml" not in str(relative):
            issues.append(f"{relative} 含供应商 SMTP 细节，必须留在本地配置")
        if PERSONAL_PROFILE_RE.search(text) and path.suffix not in {".pyc"}:
            if path.name.startswith("test_"):
                issues.append(f"{relative} 含个人化 SMTP profile 名，测试也应改为通用 profile")
            elif "email_config.local.yaml" not in str(relative):
                issues.append(f"{relative} 含个人化 SMTP profile 名，应改为通用 profile")

    notes.append("重要信息固定位置: config/content, config/integrations, config/runtime, docs, ops, scripts")
    notes.append("忽略本地配置后，源码应只保留占位和模板，不保留真实身份信息")
    return issues, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the engineering harness rules for this project.")
    parser.add_argument("--project-root", default=str(SKILL_DIR))
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    issues, notes = build_report(Path(args.project_root))
    payload = {"issues": issues, "notes": notes}

    if args.json_output:
        Path(args.json_output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# Harness Check", "", "## Issues"]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- No harness issues detected.")
    lines.extend(["", "## Notes"])
    lines.extend(f"- {note}" for note in notes)
    report = "\n".join(lines) + "\n"

    if args.markdown_output:
        Path(args.markdown_output).write_text(report, encoding="utf-8")

    print(report, end="")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
