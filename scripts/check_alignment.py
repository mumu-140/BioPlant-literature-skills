#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from run_production_digest import SKILL_DIR
except ModuleNotFoundError:
    from scripts.run_production_digest import SKILL_DIR
try:
    from project_layout import canonical_paths
except ModuleNotFoundError:
    from scripts.project_layout import canonical_paths
try:
    from project_layout import load_runtime_config
except ModuleNotFoundError:
    from scripts.project_layout import load_runtime_config
try:
    from check_harness import build_report as build_harness_report
except ModuleNotFoundError:
    from scripts.check_harness import build_report as build_harness_report


AUTOMATION_PATH = Path.home() / ".codex" / "automations" / "bio-digest-optimizer" / "automation.toml"
CANONICAL_PATHS = canonical_paths()
STALE_CHECKS = [
    ("automation", "last 24 hours", "应改为北京时间前一日 00:00 到当日 08:00 的日报窗口"),
    ("automation", "review queue is empty", "当前生产版允许把不确定项排到末尾后继续发送"),
    ("automation", "daily_review.csv", "自动化应以 review_backlog.xlsx 为人工审核主入口"),
    ("automation", " reading reviews/backlog/", "自动化应切到 Stage 1 后的 var/reviews/backlog/ 路径"),
    ("automation", "selection-json reviews/backlog/", "自动化应切到 Stage 1 后的 var/reviews/backlog/ 路径"),
    ("automation", " reviews/daily-reviews/", "自动化应切到 Stage 1 后的 var/reviews/daily-reviews/ 路径"),
    ("automation", "references/category_rules.yaml", "自动化应更新 config/content/category_rules.yaml"),
    ("automation", "references/bio_translation_glossary.yaml", "自动化应更新 config/content/bio_translation_glossary.yaml"),
    ("skill", "last 24 hours relative to the scheduled run time", "技能文档应与日报窗口保持一致"),
    ("skill", "Only send `keep` records", "技能文档应说明生产模式可带 review 项发送并排到最后"),
]


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_report(*, require_automation: bool = False) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    notes: list[str] = []

    env_path = CANONICAL_PATHS["env_file_local"]
    email_path = CANONICAL_PATHS["email_config_local"]
    users_path = CANONICAL_PATHS["users_config_local"]
    style_path = CANONICAL_PATHS["email_style_local"]
    google_path = CANONICAL_PATHS["translation_google_local"]
    runtime_override_path = CANONICAL_PATHS["runtime_config_local"]
    skill_path = SKILL_DIR / "SKILL.md"

    required_paths = {
        "env": env_path,
        "email_config": email_path,
        "users_config": users_path,
        "style_config": style_path,
    }
    for label, path in required_paths.items():
        if not path.exists():
            issues.append(f"缺少本地生产配置 `{label}`: {path}")
    if not runtime_override_path.exists():
        issues.append(f"缺少 Stage 1 runtime override: {runtime_override_path}")

    legacy_paths = [
        SKILL_DIR / ".env.local",
        SKILL_DIR / "config" / "runtime" / "production.local.yaml",
    ]
    legacy_paths.extend((SKILL_DIR / "config" / "integrations").glob("*.local.yaml"))
    for path in legacy_paths:
        if path.exists():
            issues.append(f"Stage 1 禁止 legacy 本地配置残留: {path}")

    runtime = load_runtime_config(runtime_override_path)
    runtime_paths = runtime.get("paths", {})
    runtime_environment = runtime.get("environment", {})
    runtime_database = runtime.get("database", {})

    env_file_value = Path(str(runtime_environment.get("env_file", "") or "")).resolve()
    if env_file_value != env_path.resolve():
        issues.append(f"runtime environment.env_file 必须指向 {env_path}, 当前为 {env_file_value}")

    strict_path_roots = {
        "work_dir": SKILL_DIR / "var",
        "archive_dir": SKILL_DIR / "var",
        "review_workspace_dir": SKILL_DIR / "var",
        "backlog_dir": SKILL_DIR / "var",
        "email_config": SKILL_DIR / "local" / "integrations",
        "users_config": SKILL_DIR / "local" / "integrations",
        "style_config": SKILL_DIR / "local" / "integrations",
        "summary_config": SKILL_DIR / "local" / "integrations",
    }
    for key, root in strict_path_roots.items():
        value = str(runtime_paths.get(key, "") or "").strip()
        if not value:
            issues.append(f"runtime paths.{key} 不能为空")
            continue
        resolved = Path(value).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            issues.append(f"runtime paths.{key} 必须位于 {root}, 当前为 {resolved}")

    sqlite_value = str(runtime_database.get("sqlite_path", "") or "").strip()
    if sqlite_value:
        sqlite_path = Path(sqlite_value).resolve()
        try:
            sqlite_path.relative_to((SKILL_DIR / "var").resolve())
        except ValueError:
            issues.append(f"runtime database.sqlite_path 必须位于 {SKILL_DIR / 'var'}, 当前为 {sqlite_path}")

    automation_text = read_text(AUTOMATION_PATH)
    if not automation_text:
        if require_automation:
            issues.append(f"未找到自动化配置: {AUTOMATION_PATH}")
        else:
            notes.append(f"自动化配置未找到，按非自动化环境跳过: {AUTOMATION_PATH}")
    else:
        notes.append(f"已检测自动化配置: {AUTOMATION_PATH}")
        required_automation_terms = [
            "refresh_review_backlog.py",
            "var/reviews/backlog/review_backlog.xlsx",
            "var/reviews/backlog/review_backlog_state.json",
            "selection-json",
            "finalize_review_backlog.py",
            "config/content/category_rules.yaml",
            "config/content/bio_translation_glossary.yaml",
        ]
        for term in required_automation_terms:
            if term not in automation_text:
                issues.append(f"automation 缺少关键步骤 `{term}`")

    skill_text = read_text(skill_path)

    for scope, needle, fix_hint in STALE_CHECKS:
        haystack = automation_text if scope == "automation" else skill_text
        if scope == "automation" and not automation_text:
            continue
        if needle in haystack:
            issues.append(f"{scope} 仍含过期语义 `{needle}`: {fix_hint}")

    if google_path.exists():
        notes.append(f"主翻译配置可用: {google_path}")
    else:
        notes.append("Google 本地翻译配置不存在，生产运行将依赖 runtime 配置中的其他 provider")

    notes.append(
        "生产入口命令: "
        f"{sys.executable} {SKILL_DIR / 'scripts' / 'run_production_digest.py'}"
    )

    harness_issues, harness_notes = build_harness_report(SKILL_DIR)
    issues.extend(harness_issues)
    notes.extend(f"harness: {note}" for note in harness_notes)
    return issues, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether automation, docs, and local configs align.")
    parser.add_argument("--markdown-output")
    parser.add_argument("--require-automation", action="store_true")
    args = parser.parse_args()

    issues, notes = build_report(require_automation=bool(args.require_automation))
    lines = ["# Alignment Check", ""]
    if issues:
        lines.append("## Issues")
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("## Issues")
        lines.append("- No alignment issues detected.")
    lines.append("")
    lines.append("## Notes")
    lines.extend(f"- {note}" for note in notes)
    lines.append("")
    report = "\n".join(lines) + "\n"

    if args.markdown_output:
        Path(args.markdown_output).write_text(report, encoding="utf-8")
    print(report, end="")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
