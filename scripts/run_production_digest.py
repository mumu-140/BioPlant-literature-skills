#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from with_env import SKILL_DIR, load_env_file
except ModuleNotFoundError:
    from scripts.with_env import SKILL_DIR, load_env_file


SCRIPT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = SKILL_DIR / ".venv" / "bin" / "python3"
DEFAULT_WORK_DIR = Path("/tmp/bio-digest-prod")
DEFAULT_ARCHIVE_DIR = SKILL_DIR / "archives" / "daily-digests"


def default_python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def build_command(args: argparse.Namespace) -> list[str]:
    references_dir = SKILL_DIR / "references"
    command = [
        default_python(),
        str(SCRIPT_DIR / "run_digest.py"),
        "--work-dir",
        str(Path(args.work_dir).resolve()),
        "--email-config",
        str(Path(args.email_config).resolve()),
        "--smtp-profile",
        args.smtp_profile,
        "--style-config",
        str(Path(args.style_config).resolve()),
        "--window-mode",
        args.window_mode,
        "--timezone",
        args.timezone,
        "--delivery-time",
        args.delivery_time,
        "--review-provider",
        args.review_provider,
    ]

    if args.window_mode == "lookback":
        command.extend(["--lookback-hours", str(args.lookback_hours)])
    if args.window_start or args.window_end:
        if not (args.window_start and args.window_end):
            raise SystemExit("--window-start and --window-end must be provided together")
        command.extend(["--window-start", args.window_start, "--window-end", args.window_end])

    if args.allow_review_pending:
        command.append("--allow-review-pending")

    if args.skip_email:
        command.append("--skip-email")

    if args.input_file:
        command.extend(["--input-file", str(Path(args.input_file).resolve())])

    if args.manual_review_csv:
        command.extend(["--manual-review-csv", str(Path(args.manual_review_csv).resolve())])

    summary_provider = args.summary_provider
    summary_config = Path(args.summary_config).resolve() if args.summary_config else None
    if not summary_provider:
        google_config = references_dir / "translation_google_basic_v2.local.yaml"
        tencent_config = references_dir / "translation_tencent_tmt.local.yaml"
        if google_config.exists():
            summary_provider = "google-basic-v2"
            summary_config = google_config
        elif tencent_config.exists():
            summary_provider = "tencent-tmt"
            summary_config = tencent_config
        else:
            summary_provider = "placeholder"

    command.extend(["--summary-provider", summary_provider])
    if summary_config:
        command.extend(["--summary-config", str(summary_config)])

    return command


def resolve_archive_date(args: argparse.Namespace) -> str:
    tz = ZoneInfo(args.timezone)
    if args.window_end:
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))
        return window_end.astimezone(tz).strftime("%Y-%m-%d")
    return datetime.now(tz).strftime("%Y-%m-%d")


def archive_outputs(args: argparse.Namespace) -> None:
    work_dir = Path(args.work_dir).resolve()
    archive_root = Path(args.archive_dir).resolve()
    archive_date = resolve_archive_date(args)
    target_dir = archive_root / archive_date
    target_dir.mkdir(parents=True, exist_ok=True)

    for filename in ["digest.html", "digest.csv", "digest.xlsx", "review_queue.csv"]:
        source = work_dir / filename
        if source.exists():
            shutil.copy2(source, target_dir / filename)

    tz = ZoneInfo(args.timezone)
    cutoff_date = (datetime.now(tz).date() - timedelta(days=args.retention_days))
    for child in archive_root.iterdir():
        if not child.is_dir():
            continue
        try:
            child_date = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if child_date <= cutoff_date:
            shutil.rmtree(child)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stable production entry point for scheduled or manual digest runs."
    )
    parser.add_argument("--env-file", default=str(SKILL_DIR / ".env.local"))
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument(
        "--email-config",
        default=str(SKILL_DIR / "references" / "email_config.local.yaml"),
    )
    parser.add_argument("--smtp-profile", default="qq_mail")
    parser.add_argument(
        "--style-config",
        default=str(SKILL_DIR / "references" / "email_style.local.yaml"),
    )
    parser.add_argument("--summary-provider")
    parser.add_argument("--summary-config")
    parser.add_argument("--review-provider", default="placeholder")
    parser.add_argument("--window-mode", choices=["schedule", "lookback"], default="schedule")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--delivery-time", default="08:00")
    parser.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--input-file")
    parser.add_argument("--manual-review-csv")
    parser.add_argument("--allow-review-pending", action="store_true", default=True)
    parser.add_argument("--no-allow-review-pending", action="store_false", dest="allow_review_pending")
    parser.add_argument("--skip-email", action="store_true")
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()

    load_env_file(Path(args.env_file).resolve())
    command = build_command(args)
    print("[production] running stable digest entrypoint")
    print("[production] command:", " ".join(command))
    if args.print_command:
        return 0
    completed = subprocess.run(command)
    if completed.returncode == 0:
        archive_outputs(args)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
