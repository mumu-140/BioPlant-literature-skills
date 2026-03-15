#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from run_production_digest import SKILL_DIR
except ModuleNotFoundError:
    from scripts.run_production_digest import SKILL_DIR


AUTOMATION_PATH = Path.home() / ".codex" / "automations" / "bio-digest-daily" / "automation.toml"
STALE_CHECKS = [
    ("automation", "last 24 hours", "应改为北京时间前一日 00:00 到当日 08:00 的日报窗口"),
    ("automation", "review queue is empty", "当前生产版允许把不确定项排到末尾后继续发送"),
    ("skill", "last 24 hours relative to the scheduled run time", "技能文档应与日报窗口保持一致"),
    ("skill", "Only send `keep` records", "技能文档应说明生产模式可带 review 项发送并排到最后"),
]


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_report() -> tuple[list[str], list[str]]:
    issues: list[str] = []
    notes: list[str] = []

    env_path = SKILL_DIR / ".env.local"
    email_config = SKILL_DIR / "references" / "email_config.local.yaml"
    style_config = SKILL_DIR / "references" / "email_style.local.yaml"
    google_config = SKILL_DIR / "references" / "translation_google_basic_v2.local.yaml"
    skill_path = SKILL_DIR / "SKILL.md"

    for required_path in [env_path, email_config, style_config]:
        if not required_path.exists():
            issues.append(f"缺少本地生产配置: {required_path}")

    automation_text = read_text(AUTOMATION_PATH)
    if not automation_text:
        issues.append(f"未找到自动化配置: {AUTOMATION_PATH}")
    else:
        notes.append(f"已检测自动化配置: {AUTOMATION_PATH}")

    skill_text = read_text(skill_path)

    for scope, needle, fix_hint in STALE_CHECKS:
        haystack = automation_text if scope == "automation" else skill_text
        if needle in haystack:
            issues.append(f"{scope} 仍含过期语义 `{needle}`: {fix_hint}")

    if google_config.exists():
        notes.append(f"主翻译配置可用: {google_config}")
    else:
        notes.append("Google 本地翻译配置不存在，将回退到其他 provider")

    notes.append(
        "生产入口命令: "
        f"{sys.executable} {SKILL_DIR / 'scripts' / 'run_production_digest.py'}"
    )
    return issues, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether automation, docs, and local configs align.")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    issues, notes = build_report()
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
