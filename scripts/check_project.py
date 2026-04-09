#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from project_layout import SKILL_DIR
except ModuleNotFoundError:
    from scripts.project_layout import SKILL_DIR
try:
    from check_alignment import build_report as build_alignment_report
except ModuleNotFoundError:
    from scripts.check_alignment import build_report as build_alignment_report
try:
    from check_harness import build_report as build_harness_report
except ModuleNotFoundError:
    from scripts.check_harness import build_report as build_harness_report


DEFAULT_TESTS = [
    "tests.test_config",
    "tests.test_harness",
    "tests.test_launchd_generator",
    "tests.test_production_entry",
    "tests.test_review_backlog_flow",
    "tests.test_send_email_recipients",
    "tests.test_sync_digest_db",
    "tests.test_with_env",
]


def run_tests(test_targets: list[str]) -> tuple[bool, str]:
    command = [sys.executable, "-m", "unittest", *test_targets]
    completed = subprocess.run(
        command,
        cwd=str(SKILL_DIR),
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, output.strip()


def build_report(
    *,
    include_tests: bool = True,
    test_targets: list[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    issues: list[str] = []
    notes: list[str] = []
    sections: list[str] = []

    harness_issues, harness_notes = build_harness_report(SKILL_DIR)
    issues.extend(harness_issues)
    notes.extend(f"harness: {note}" for note in harness_notes)

    alignment_issues, alignment_notes = build_alignment_report()
    for issue in alignment_issues:
        if issue not in issues:
            issues.append(issue)
    for note in alignment_notes:
        if note.startswith("harness: "):
            continue
        prefixed = f"alignment: {note}"
        if prefixed not in notes:
            notes.append(prefixed)

    resolved_tests = test_targets or list(DEFAULT_TESTS)
    if include_tests:
        ok, output = run_tests(resolved_tests)
        sections.append("### Critical Tests")
        sections.append(f"- Command: `{sys.executable} -m unittest {' '.join(resolved_tests)}`")
        if ok:
            notes.append("critical tests: passed")
            if output:
                sections.append("```text")
                sections.append(output)
                sections.append("```")
        else:
            issues.append("critical tests failed")
            if output:
                sections.append("```text")
                sections.append(output)
                sections.append("```")
    else:
        notes.append("critical tests: skipped by flag")

    return issues, notes, sections


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the project harness, alignment checks, and critical smoke tests.")
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Only run harness and alignment checks.",
    )
    parser.add_argument(
        "--test",
        action="append",
        default=[],
        help="Override default unittest target(s). Can be passed multiple times.",
    )
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    issues, notes, sections = build_report(
        include_tests=not args.skip_tests,
        test_targets=args.test or None,
    )
    payload = {"issues": issues, "notes": notes, "tests": args.test or DEFAULT_TESTS}

    if args.json_output:
        Path(args.json_output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# Project Check", "", "## Issues"]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- No project issues detected.")
    lines.extend(["", "## Notes"])
    lines.extend(f"- {note}" for note in notes)
    if sections:
        lines.extend(["", "## Details", *sections])
    report = "\n".join(lines) + "\n"

    if args.markdown_output:
        Path(args.markdown_output).write_text(report, encoding="utf-8")

    print(report, end="")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
