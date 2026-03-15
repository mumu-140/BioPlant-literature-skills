#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common import compute_scheduled_digest_window, isoformat_utc, load_yaml_file

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PYTHON = sys.executable


def run_step(label: str, command: list[str]) -> None:
    print(f"[run] {label}")
    subprocess.run(command, check=True)


def count_jsonl_rows(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def merge_jsonl(output_path: Path, input_paths: list[Path]) -> int:
    merged_lines: list[str] = []
    for path in input_paths:
        if not path.exists():
            continue
        merged_lines.extend(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    text = ("\n".join(merged_lines) + "\n") if merged_lines else ""
    output_path.write_text(text, encoding="utf-8")
    return len(merged_lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the end-to-end digest pipeline.")
    parser.add_argument("--work-dir", required=True, help="Output directory for this run")
    parser.add_argument("--watchlist", default=str(SKILL_DIR / "references" / "journal_watchlist.yaml"))
    parser.add_argument("--rules", default=str(SKILL_DIR / "references" / "category_rules.yaml"))
    parser.add_argument("--email-config", default=str(SKILL_DIR / "references" / "email_config.example.yaml"))
    parser.add_argument("--template", default=str(SKILL_DIR / "assets" / "email_template.html"))
    parser.add_argument("--style-config", default=str(SKILL_DIR / "references" / "email_style.local.yaml"))
    parser.add_argument("--input-file", help="Optional pre-fetched raw JSONL file")
    parser.add_argument("--smtp-profile", help="SMTP profile to use for sending")
    parser.add_argument("--skip-email", action="store_true", help="Skip the email sending step")
    parser.add_argument("--manual-review-csv", help="Edited review_queue.csv with final human/Codex decisions")
    parser.add_argument("--allow-review-pending", action="store_true", help="Allow email sending even if review queue is non-empty")
    parser.add_argument("--review-provider", choices=["placeholder", "command", "http-json"], default="placeholder")
    parser.add_argument("--review-command", help="External command for llm_review.py")
    parser.add_argument("--review-config", help="Config file for LLM review provider")
    parser.add_argument("--summary-provider", choices=["placeholder", "command", "http-json", "tencent-tmt", "google-basic-v2"], default="placeholder")
    parser.add_argument("--summary-command", help="External command for translate_and_summarize.py")
    parser.add_argument("--summary-config", help="Config file for translation/summarization provider")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--window-mode", choices=["schedule", "lookback"], default="schedule")
    parser.add_argument("--window-start", help="Explicit UTC window start, e.g. 2026-03-13T16:00:00Z")
    parser.add_argument("--window-end", help="Explicit UTC window end, e.g. 2026-03-15T00:00:00Z")
    parser.add_argument("--timezone", help="Timezone used for scheduled digest windows")
    parser.add_argument("--delivery-time", help="Scheduled digest delivery time in HH:MM")
    args = parser.parse_args()

    run_dir = Path(args.work_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_path = run_dir / "raw_records.jsonl"
    normalized_path = run_dir / "normalized_records.jsonl"
    duplicates_path = run_dir / "duplicates.jsonl"
    filtered_path = run_dir / "filtered_records.jsonl"
    rejected_path = run_dir / "rejected_records.jsonl"
    classified_path = run_dir / "classified_records.jsonl"
    reviewed_path = run_dir / "reviewed_records.jsonl"
    llm_keep_path = run_dir / "llm_keep_records.jsonl"
    review_queue_path = run_dir / "review_queue.jsonl"
    llm_reject_path = run_dir / "llm_reject_records.jsonl"
    final_reviewed_path = run_dir / "final_reviewed_records.jsonl"
    final_keep_path = run_dir / "final_keep_records.jsonl"
    final_review_queue_path = run_dir / "final_review_queue.jsonl"
    final_reject_path = run_dir / "final_reject_records.jsonl"
    digest_input_path = run_dir / "digest_input_records.jsonl"
    localized_path = run_dir / "localized_records.jsonl"
    html_path = run_dir / "digest.html"
    csv_path = run_dir / "digest.csv"
    xlsx_path = run_dir / "digest.xlsx"
    review_html_path = run_dir / "review_queue.html"
    review_csv_path = run_dir / "review_queue.csv"
    review_xlsx_path = run_dir / "review_queue.xlsx"
    feedback_report_path = run_dir / "rule_feedback_report.md"
    classification_suggestions_md_path = run_dir / "classification_suggestions.md"
    classification_suggestions_json_path = run_dir / "classification_suggestions.json"
    glossary_candidates_yaml_path = run_dir / "glossary_candidates.yaml"
    glossary_candidates_report_path = run_dir / "glossary_candidates.md"
    watchlist_data = load_yaml_file(args.watchlist) or {}
    watchlist_defaults = watchlist_data.get("defaults", {})
    digest_timezone = args.timezone or watchlist_defaults.get("timezone", "Asia/Shanghai")
    delivery_time = args.delivery_time or watchlist_defaults.get("delivery_time", "08:00")
    window_start = ""
    window_end = ""
    if args.window_start or args.window_end:
        if not (args.window_start and args.window_end):
            raise SystemExit("--window-start and --window-end must be provided together")
        window_start = args.window_start
        window_end = args.window_end
        print(f"[window] {window_start} -> {window_end} (explicit)")
    elif args.window_mode == "schedule":
        window_start_dt, window_end_dt = compute_scheduled_digest_window(digest_timezone, delivery_time)
        window_start = isoformat_utc(window_start_dt)
        window_end = isoformat_utc(window_end_dt)
        print(f"[window] {window_start} -> {window_end} ({digest_timezone} schedule {delivery_time})")

    if args.input_file:
        raw_path.write_text(Path(args.input_file).read_text(encoding="utf-8"), encoding="utf-8")
    else:
        fetch_command = [
            PYTHON,
            str(SCRIPT_DIR / "fetch_feeds.py"),
            "--watchlist",
            args.watchlist,
            "--output",
            str(raw_path),
        ]
        if window_start and window_end:
            fetch_command.extend(["--window-start", window_start, "--window-end", window_end])
        elif args.lookback_hours is not None:
            fetch_command.extend(["--lookback-hours", str(args.lookback_hours)])
        run_step("fetch_feeds", fetch_command)

    normalize_command = [
        PYTHON,
        str(SCRIPT_DIR / "normalize_and_dedupe.py"),
        "--input",
        str(raw_path),
        "--output",
        str(normalized_path),
        "--duplicates-output",
        str(duplicates_path),
    ]
    if window_start and window_end:
        normalize_command.extend(["--window-start", window_start, "--window-end", window_end])
    else:
        normalize_command.extend(["--lookback-hours", str(args.lookback_hours)])
    run_step("normalize_and_dedupe", normalize_command)
    run_step(
        "filter_bio_relevance",
        [
            PYTHON,
            str(SCRIPT_DIR / "filter_bio_relevance.py"),
            "--input",
            str(normalized_path),
            "--rules",
            args.rules,
            "--watchlist",
            args.watchlist,
            "--output",
            str(filtered_path),
            "--rejected-output",
            str(rejected_path),
        ],
    )
    run_step(
        "classify_papers",
        [
            PYTHON,
            str(SCRIPT_DIR / "classify_papers.py"),
            "--input",
            str(filtered_path),
            "--rules",
            args.rules,
            "--output",
            str(classified_path),
        ],
    )
    review_command = [
        PYTHON,
        str(SCRIPT_DIR / "llm_review.py"),
        "--input",
        str(classified_path),
        "--output",
        str(reviewed_path),
        "--keep-output",
        str(llm_keep_path),
        "--review-output",
        str(review_queue_path),
        "--reject-output",
        str(llm_reject_path),
        "--provider",
        args.review_provider,
    ]
    if args.review_provider == "command":
        if not args.review_command:
            raise SystemExit("--review-command is required when --review-provider=command")
        review_command.extend(["--command", args.review_command])
    if args.review_provider == "http-json":
        if not args.review_config:
            raise SystemExit("--review-config is required when --review-provider=http-json")
        review_command.extend(["--config", args.review_config])
    run_step("llm_review", review_command)
    run_step(
        "rule_feedback_report",
        [
            PYTHON,
            str(SCRIPT_DIR / "rule_feedback_report.py"),
            "--input",
            str(reviewed_path),
            "--output",
            str(feedback_report_path),
        ],
    )
    run_step(
        "classification_suggestions",
        [
            PYTHON,
            str(SCRIPT_DIR / "classification_suggestions.py"),
            "--classified",
            str(classified_path),
            "--reviewed",
            str(reviewed_path),
            "--markdown-output",
            str(classification_suggestions_md_path),
            "--json-output",
            str(classification_suggestions_json_path),
        ],
    )
    if args.manual_review_csv:
        run_step(
            "apply_manual_decisions",
            [
                PYTHON,
                str(SCRIPT_DIR / "apply_manual_decisions.py"),
                "--input",
                str(reviewed_path),
                "--decisions-csv",
                args.manual_review_csv,
                "--output",
                str(final_reviewed_path),
                "--keep-output",
                str(final_keep_path),
                "--review-output",
                str(final_review_queue_path),
                "--reject-output",
                str(final_reject_path),
            ],
        )
    else:
        final_reviewed_path.write_text(reviewed_path.read_text(encoding="utf-8"), encoding="utf-8")
        final_keep_path.write_text(llm_keep_path.read_text(encoding="utf-8"), encoding="utf-8")
        final_review_queue_path.write_text(review_queue_path.read_text(encoding="utf-8"), encoding="utf-8")
        final_reject_path.write_text(llm_reject_path.read_text(encoding="utf-8"), encoding="utf-8")
    if args.allow_review_pending and count_jsonl_rows(final_review_queue_path):
        merged_count = merge_jsonl(digest_input_path, [final_keep_path, final_review_queue_path])
        print(f"[digest] including review-pending records at the end ({merged_count} total)")
    else:
        digest_input_path.write_text(final_keep_path.read_text(encoding="utf-8"), encoding="utf-8")
    summarize_command = [
        PYTHON,
        str(SCRIPT_DIR / "translate_and_summarize.py"),
        "--input",
        str(digest_input_path),
        "--rules",
        args.rules,
        "--output",
        str(localized_path),
        "--provider",
        args.summary_provider,
    ]
    if args.summary_provider == "command" and args.summary_command:
        summarize_command.extend(["--command", args.summary_command])
    if args.summary_provider in {"http-json", "tencent-tmt", "google-basic-v2"}:
        if not args.summary_config:
            raise SystemExit(f"--summary-config is required when --summary-provider={args.summary_provider}")
        summarize_command.extend(["--config", args.summary_config])
    run_step("translate_and_summarize", summarize_command)
    glossary_path = ""
    if args.summary_config:
        summary_config_data = load_yaml_file(args.summary_config) or {}
        glossary_path = str(summary_config_data.get("glossary_path", "") or "")
    if glossary_path:
        run_step(
            "build_glossary_candidates",
            [
                PYTHON,
                str(SCRIPT_DIR / "build_glossary_candidates.py"),
                "--input",
                str(localized_path),
                "--glossary",
                glossary_path,
                "--yaml-output",
                str(glossary_candidates_yaml_path),
                "--report-output",
                str(glossary_candidates_report_path),
            ],
        )
    run_step(
        "export_digest",
        [
            PYTHON,
            str(SCRIPT_DIR / "export_digest.py"),
            "--input",
            str(localized_path),
            "--rules",
            args.rules,
            "--html-output",
            str(html_path),
            "--csv-output",
            str(csv_path),
            "--xlsx-output",
            str(xlsx_path),
            "--template",
            args.template,
            "--style-config",
            args.style_config,
        ],
    )
    run_step(
        "export_review_queue",
        [
            PYTHON,
            str(SCRIPT_DIR / "export_digest.py"),
            "--input",
            str(final_review_queue_path),
            "--rules",
            args.rules,
            "--html-output",
            str(review_html_path),
            "--csv-output",
            str(review_csv_path),
            "--xlsx-output",
            str(review_xlsx_path),
            "--template",
            args.template,
            "--style-config",
            args.style_config,
            "--schema-key",
            "review_queue_schema",
        ],
    )

    if not args.skip_email:
        if count_jsonl_rows(final_review_queue_path) and not args.allow_review_pending:
            raise SystemExit("review_queue is not empty; resolve manual/Codex review first or pass --allow-review-pending")
        if not args.smtp_profile:
            raise SystemExit("--smtp-profile is required unless --skip-email is set")
        subject = f"[Bio Digest] {datetime.now().strftime('%Y-%m-%d')} Daily Literature Update"
        run_step(
            "send_email",
            [
                PYTHON,
                str(SCRIPT_DIR / "send_email.py"),
                "--config",
                args.email_config,
                "--profile",
                args.smtp_profile,
                "--html-body",
                str(html_path),
                "--csv-attachment",
                str(csv_path),
                "--xlsx-attachment",
                str(xlsx_path),
                "--subject",
                subject,
            ],
        )

    print(f"[done] artifacts written to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
