#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

try:
    from scripts._bootstrap import SKILL_DIR, DEFAULT_RUNTIME_CONFIG_PATH, canonical_paths, load_runtime_config
except ModuleNotFoundError:
    from _bootstrap import SKILL_DIR, DEFAULT_RUNTIME_CONFIG_PATH, canonical_paths, load_runtime_config
try:
    from scripts.common import current_timestamp_utc
except ModuleNotFoundError:
    from common import current_timestamp_utc
try:
    from scripts.with_env import load_env_file
except ModuleNotFoundError:
    from with_env import load_env_file

from bio_literature_digest.review.backlog import (
    DEFAULT_ARCHIVE_DIR as REVIEW_DEFAULT_ARCHIVE_DIR,
    DEFAULT_BACKLOG_DIR as REVIEW_DEFAULT_BACKLOG_DIR,
    DEFAULT_REVIEW_WORKSPACE_DIR as REVIEW_DEFAULT_REVIEW_WORKSPACE_DIR,
    archive_outputs as canonical_archive_outputs,
    export_backlog_views as canonical_export_backlog_views,
    load_review_rows as canonical_load_review_rows,
    resolve_archive_date as canonical_resolve_archive_date,
    write_backlog_csv as canonical_write_backlog_csv,
)


SCRIPT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = SKILL_DIR / ".venv" / "bin" / "python3"
CANONICAL_PATHS = canonical_paths()
RUNTIME_DEFAULTS = load_runtime_config(DEFAULT_RUNTIME_CONFIG_PATH)
DEFAULT_WORK_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("work_dir", SKILL_DIR / "var" / "work" / "current")))
DEFAULT_ARCHIVE_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("archive_dir", REVIEW_DEFAULT_ARCHIVE_DIR)))
DEFAULT_REVIEW_WORKSPACE_DIR = Path(
    str(RUNTIME_DEFAULTS.get("paths", {}).get("review_workspace_dir", REVIEW_DEFAULT_REVIEW_WORKSPACE_DIR))
)
DEFAULT_BACKLOG_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("backlog_dir", REVIEW_DEFAULT_BACKLOG_DIR)))
RUN_LOCK_FILENAME = ".run_production_digest.lock"


def default_python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def load_lock_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_run_lock(work_dir: Path, stale_hours: int) -> Path:
    stale_seconds = max(1, stale_hours) * 3600
    work_dir.mkdir(parents=True, exist_ok=True)
    lock_path = work_dir / RUN_LOCK_FILENAME
    payload = {
        "pid": os.getpid(),
        "started_at_utc": current_timestamp_utc(),
    }
    attempts = 0
    while attempts < 2:
        attempts += 1
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            return lock_path
        except FileExistsError:
            existing = load_lock_payload(lock_path)
            existing_pid = int(existing.get("pid") or 0)
            active = is_pid_running(existing_pid)
            stale = False
            try:
                stale = (time.time() - lock_path.stat().st_mtime) > stale_seconds
            except OSError:
                stale = True
            if not active or stale:
                try:
                    lock_path.unlink()
                    continue
                except FileNotFoundError:
                    continue
            raise SystemExit(
                f"another run is active (pid={existing_pid}). lock={lock_path}; "
                "retry later or remove stale lock manually"
            )
    raise SystemExit(f"failed to acquire run lock after cleanup attempts: {lock_path}")


def release_run_lock(lock_path: Path) -> None:
    try:
        existing = load_lock_payload(lock_path)
        if int(existing.get("pid") or 0) not in {0, os.getpid()}:
            return
        lock_path.unlink(missing_ok=True)
    except OSError:
        return


def default_web_project_root() -> Path:
    env_override = os.environ.get("BIO_DIGEST_WEB_ROOT", "").strip()
    if env_override:
        return Path(env_override).resolve()
    configured_root = str(RUNTIME_DEFAULTS.get("web", {}).get("project_root", "") or "").strip()
    if configured_root:
        return Path(configured_root).resolve()
    raise RuntimeError("web.project_root is empty in runtime config; set it explicitly before enabling web sync")


def apply_runtime_defaults(args: argparse.Namespace) -> argparse.Namespace:
    config = load_runtime_config(args.runtime_config)
    paths = config.get("paths", {})
    delivery = config.get("delivery", {})
    providers = config.get("providers", {})
    environment = config.get("environment", {})
    web = config.get("web", {})
    database = config.get("database", {})

    if not getattr(args, "env_file", None):
        args.env_file = str(environment.get("env_file", "") or "")
    if not getattr(args, "work_dir", None):
        args.work_dir = str(paths.get("work_dir", "") or "")
    if not getattr(args, "archive_dir", None):
        args.archive_dir = str(paths.get("archive_dir", "") or "")
    if not getattr(args, "review_workspace_dir", None):
        args.review_workspace_dir = str(paths.get("review_workspace_dir", "") or "")
    if not getattr(args, "backlog_dir", None):
        args.backlog_dir = str(paths.get("backlog_dir", "") or "")
    if not getattr(args, "watchlist", None):
        args.watchlist = str(paths.get("watchlist", "") or CANONICAL_PATHS["watchlist"])
    if not getattr(args, "rules", None):
        args.rules = str(paths.get("rules", "") or CANONICAL_PATHS["rules"])
    if not getattr(args, "email_config", None):
        args.email_config = str(paths.get("email_config", "") or CANONICAL_PATHS["email_config_local"])
    if not getattr(args, "users_config", None):
        args.users_config = str(paths.get("users_config", "") or CANONICAL_PATHS["users_config_local"])
    if not getattr(args, "style_config", None):
        args.style_config = str(paths.get("style_config", "") or CANONICAL_PATHS["email_style_local"])
    if not getattr(args, "template", None):
        args.template = str(paths.get("template", "") or CANONICAL_PATHS["email_template"])
    if not getattr(args, "summary_config", None):
        args.summary_config = str(paths.get("summary_config", "") or CANONICAL_PATHS["nvidia_ai_config_local"])

    if not getattr(args, "smtp_profile", None):
        args.smtp_profile = str(delivery.get("smtp_profile", "") or "primary_smtp")
    if not getattr(args, "timezone", None):
        args.timezone = str(delivery.get("timezone", "") or "Asia/Shanghai")
    if not getattr(args, "delivery_time", None):
        args.delivery_time = str(delivery.get("delivery_time", "") or "08:00")
    if not getattr(args, "window_policy", None):
        args.window_policy = str(delivery.get("window_policy", "") or "previous_day")
    if not getattr(args, "allow_review_pending_explicit", False):
        args.allow_review_pending = bool(delivery.get("allow_review_pending", True))

    if not getattr(args, "review_provider", None):
        args.review_provider = str(providers.get("review_provider", "") or "placeholder")
    if not getattr(args, "summary_provider", None):
        args.summary_provider = str(providers.get("summary_provider", "") or "nvidia-chat")

    if not getattr(args, "web_base_url", None):
        args.web_base_url = str(web.get("base_url", "") or "")
    if not getattr(args, "web_project_root", None):
        args.web_project_root = str(web.get("project_root", "") or "")
    if not getattr(args, "sync_web_explicit", False):
        args.sync_web = bool(web.get("sync_enabled", False))
    if not getattr(args, "database_path", None):
        args.database_path = str(database.get("sqlite_path", "") or "")
    if not getattr(args, "sync_db_explicit", False):
        args.sync_db = bool(database.get("enabled", False))

    args.runtime_defaults = config
    return args


def resolve_web_sync_settings(project_root: Path | None = None) -> SimpleNamespace:
    resolved_root = (project_root or default_web_project_root()).resolve()
    tools_dir = resolved_root / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    try:
        from instance_paths import get_instance_paths  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"Missing web tooling module under {tools_dir}: instance_paths") from exc

    instance_paths = get_instance_paths(resolved_root)
    backend_dir = resolved_root / "backend"
    return SimpleNamespace(
        project_root=resolved_root,
        importer=backend_dir / "import_digest_run.py",
        importer_python=backend_dir / ".venv" / "bin" / "python",
        backend_env_file=instance_paths.backend_env_file,
    )


def build_command(args: argparse.Namespace) -> list[str]:
    email_config = Path(
        str(getattr(args, "email_config", "") or CANONICAL_PATHS["email_config_local"])
    ).resolve()
    users_config = Path(
        str(getattr(args, "users_config", "") or CANONICAL_PATHS["users_config_local"])
    ).resolve()
    style_config = Path(
        str(getattr(args, "style_config", "") or CANONICAL_PATHS["email_style_local"])
    ).resolve()
    watchlist = Path(str(getattr(args, "watchlist", "") or CANONICAL_PATHS["watchlist"])).resolve()
    rules = Path(str(getattr(args, "rules", "") or CANONICAL_PATHS["rules"])).resolve()
    template = Path(str(getattr(args, "template", "") or CANONICAL_PATHS["email_template"])).resolve()
    command = [
        default_python(),
        str(SCRIPT_DIR / "run_digest.py"),
        "--work-dir",
        str(Path(args.work_dir).resolve()),
        "--watchlist",
        str(watchlist),
        "--rules",
        str(rules),
        "--email-config",
        str(email_config),
        "--users-config",
        str(users_config),
        "--smtp-profile",
        args.smtp_profile,
        "--style-config",
        str(style_config),
        "--template",
        str(template),
        "--window-mode",
        args.window_mode,
        "--timezone",
        args.timezone,
        "--delivery-time",
        args.delivery_time,
        "--window-policy",
        str(getattr(args, "window_policy", "") or "previous_day"),
        "--review-provider",
        args.review_provider,
    ]
    web_base_url = str(getattr(args, "web_base_url", "") or "").strip()
    if web_base_url:
        command.extend(["--web-base-url", web_base_url])

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
        nvidia_config = CANONICAL_PATHS["nvidia_ai_config_local"]
        google_config = CANONICAL_PATHS["translation_google_local"] if CANONICAL_PATHS["translation_google_local"].exists() else None
        tencent_config = CANONICAL_PATHS["translation_tencent_local"] if CANONICAL_PATHS["translation_tencent_local"].exists() else None
        if nvidia_config.exists():
            summary_provider = "nvidia-chat"
            summary_config = nvidia_config.resolve()
        elif google_config:
            summary_provider = "google-basic-v2"
            summary_config = google_config.resolve()
        elif tencent_config:
            summary_provider = "tencent-tmt"
            summary_config = tencent_config.resolve()
        else:
            summary_provider = "placeholder"

    command.extend(["--summary-provider", summary_provider])
    if summary_config:
        command.extend(["--summary-config", str(summary_config)])

    return command


def load_run_metadata(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def should_archive_failed_run(work_dir: Path) -> bool:
    metadata = load_run_metadata(work_dir / "run_metadata.json")
    if not metadata:
        return False
    if metadata.get("status") != "failed":
        return False
    if metadata.get("failed_step") != "send_email":
        return False
    required_outputs = [
        work_dir / "digest.html",
        work_dir / "digest.csv",
        work_dir / "digest.xlsx",
        work_dir / "daily_review.xlsx",
        work_dir / "run_metadata.json",
    ]
    return all(path.exists() for path in required_outputs)


# Use the extracted backlog module as the canonical implementation.
resolve_archive_date = canonical_resolve_archive_date
archive_outputs = canonical_archive_outputs
load_review_rows = canonical_load_review_rows
write_backlog_csv = canonical_write_backlog_csv
export_backlog_views = canonical_export_backlog_views


def resolve_web_sync_args(args: argparse.Namespace) -> SimpleNamespace:
    explicit_root = Path(args.web_project_root).resolve() if getattr(args, "web_project_root", None) else None
    defaults = resolve_web_sync_settings(explicit_root)
    return SimpleNamespace(
        project_root=defaults.project_root,
        importer=Path(args.web_importer).resolve() if getattr(args, "web_importer", None) else defaults.importer,
        importer_python=(
            Path(args.web_importer_python).resolve()
            if getattr(args, "web_importer_python", None)
            else defaults.importer_python
        ),
        backend_env_file=(
            Path(args.web_backend_env_file).resolve()
            if getattr(args, "web_backend_env_file", None)
            else defaults.backend_env_file
        ),
    )


def sync_web_digest(args: argparse.Namespace, run_dir: Path) -> None:
    settings = resolve_web_sync_args(args)
    importer_path = settings.importer
    importer_python = settings.importer_python
    if not importer_path.exists():
        raise FileNotFoundError(f"Missing web importer script: {importer_path}")
    if not importer_python.exists():
        raise FileNotFoundError(f"Missing web importer python: {importer_python}")
    command = [
        str(importer_python),
        str(importer_path),
        "--run-dir",
        str(run_dir.resolve()),
    ]
    print("[production] syncing web digest:", " ".join(command))
    subprocess.run(command, check=True)
    verify_web_digest_sync(args, run_dir)


def sync_digest_database(args: argparse.Namespace, run_dir: Path, archive_date: str) -> None:
    if not args.database_path:
        raise SystemExit("database sync is enabled but database_path is empty in runtime config")
    command = [
        default_python(),
        str(SCRIPT_DIR / "sync_digest_db.py"),
        "--run-dir",
        str(run_dir.resolve()),
        "--db-path",
        str(Path(args.database_path).resolve()),
        "--archive-date",
        archive_date,
    ]
    print("[production] syncing digest database:", " ".join(command))
    subprocess.run(command, check=True)


def resolve_web_sqlite_path(env_file: Path) -> Path:
    database_url = ""
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DATABASE_URL":
            database_url = value.strip()
            break
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"Only sqlite DATABASE_URL is supported for verification, got: {database_url}")
    sqlite_path = database_url.removeprefix("sqlite:///")
    return Path(sqlite_path).resolve()


def verify_web_digest_sync(args: argparse.Namespace, run_dir: Path) -> None:
    env_file = resolve_web_sync_args(args).backend_env_file
    if not env_file.exists():
        raise FileNotFoundError(f"Missing web backend env file for sync verification: {env_file}")
    db_path = resolve_web_sqlite_path(env_file)
    digest_csv = run_dir / "digest.csv"
    run_metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    expected_date = resolve_archive_date(args)
    expected_rows = 0
    with digest_csv.open("r", encoding="utf-8", newline="") as handle:
        expected_rows = sum(1 for _ in csv.DictReader(handle))
    with sqlite3.connect(str(db_path)) as connection:
        row = connection.execute(
            "select count(*) from paper_daily_entries where digest_date = ?",
            (expected_date,),
        ).fetchone()
    actual_rows = int(row[0] if row else 0)
    if actual_rows != expected_rows:
        raise RuntimeError(
            f"Web digest sync mismatch for {expected_date}: expected {expected_rows} rows from {digest_csv}, got {actual_rows} rows in {db_path}"
        )
    print(
        "[production] verified web sync:",
        expected_date,
        f"{actual_rows} rows",
        "matches digest.csv and email artifacts",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stable production entry point for scheduled or manual digest runs."
    )
    parser.add_argument("--runtime-config", default=str(DEFAULT_RUNTIME_CONFIG_PATH))
    parser.add_argument("--env-file")
    parser.add_argument("--work-dir")
    parser.add_argument("--watchlist")
    parser.add_argument("--rules")
    parser.add_argument("--template")
    parser.add_argument("--email-config")
    parser.add_argument("--users-config")
    parser.add_argument("--smtp-profile")
    parser.add_argument("--style-config")
    parser.add_argument("--summary-provider")
    parser.add_argument("--summary-config")
    parser.add_argument("--review-provider")
    parser.add_argument("--window-mode", choices=["schedule", "lookback"], default="schedule")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    parser.add_argument("--timezone")
    parser.add_argument("--delivery-time")
    parser.add_argument("--window-policy", choices=["previous_day", "previous_day_to_delivery"])
    parser.add_argument("--web-base-url")
    parser.add_argument("--archive-dir")
    parser.add_argument("--review-workspace-dir")
    parser.add_argument("--backlog-dir")
    parser.add_argument("--web-project-root")
    parser.add_argument("--web-importer")
    parser.add_argument("--web-importer-python")
    parser.add_argument("--web-backend-env-file")
    parser.add_argument("--sync-web", action="store_true", default=False)
    parser.add_argument("--no-sync-web", action="store_false", dest="sync_web")
    parser.add_argument("--database-path")
    parser.add_argument("--sync-db", action="store_true", default=False)
    parser.add_argument("--no-sync-db", action="store_false", dest="sync_db")
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--input-file")
    parser.add_argument("--manual-review-csv")
    parser.add_argument("--allow-review-pending", action="store_true", default=True)
    parser.add_argument("--no-allow-review-pending", action="store_false", dest="allow_review_pending")
    parser.add_argument("--skip-email", action="store_true")
    parser.add_argument("--print-command", action="store_true")
    parser.add_argument("--lock-stale-hours", type=int, default=12)
    args = parser.parse_args()

    args.sync_web_explicit = ("--sync-web" in sys.argv) or ("--no-sync-web" in sys.argv)
    args.sync_db_explicit = ("--sync-db" in sys.argv) or ("--no-sync-db" in sys.argv)
    args.allow_review_pending_explicit = (
        ("--allow-review-pending" in sys.argv) or ("--no-allow-review-pending" in sys.argv)
    )
    args = apply_runtime_defaults(args)

    load_env_file(Path(args.env_file).resolve())
    command = build_command(args)
    print("[production] running stable digest entrypoint")
    print("[production] command:", " ".join(command))
    if args.print_command:
        return 0
    work_dir = Path(args.work_dir).resolve()
    lock_path = acquire_run_lock(work_dir, args.lock_stale_hours)
    try:
        completed = subprocess.run(command)
        should_archive = completed.returncode == 0 or should_archive_failed_run(work_dir)
        if should_archive:
            archive_date = archive_outputs(args)
            if args.sync_db:
                sync_digest_database(args, work_dir, archive_date)
            if completed.returncode == 0 and args.sync_web:
                sync_web_digest(args, work_dir)
        return completed.returncode
    finally:
        release_run_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
