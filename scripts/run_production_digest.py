#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

try:
    from with_env import SKILL_DIR, load_env_file
except ModuleNotFoundError:
    from scripts.with_env import SKILL_DIR, load_env_file

try:
    from common import canonicalize_doi, canonicalize_url, current_timestamp_utc, load_yaml_file, normalize_title
except ModuleNotFoundError:
    from scripts.common import canonicalize_doi, canonicalize_url, current_timestamp_utc, load_yaml_file, normalize_title
try:
    from project_layout import DEFAULT_RUNTIME_CONFIG_PATH, canonical_paths, load_runtime_config
except ModuleNotFoundError:
    from scripts.project_layout import DEFAULT_RUNTIME_CONFIG_PATH, canonical_paths, load_runtime_config


SCRIPT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = SKILL_DIR / ".venv" / "bin" / "python3"
CANONICAL_PATHS = canonical_paths()
RUNTIME_DEFAULTS = load_runtime_config(DEFAULT_RUNTIME_CONFIG_PATH)
DEFAULT_WORK_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("work_dir", "/private/tmp/bio-literature-digest")))
DEFAULT_ARCHIVE_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("archive_dir", SKILL_DIR / "archives" / "daily-digests")))
DEFAULT_REVIEW_WORKSPACE_DIR = Path(
    str(RUNTIME_DEFAULTS.get("paths", {}).get("review_workspace_dir", SKILL_DIR / "reviews" / "daily-reviews"))
)
DEFAULT_BACKLOG_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("backlog_dir", SKILL_DIR / "reviews" / "backlog")))
EDITABLE_REVIEW_COLUMNS = [
    "interest_level",
    "interest_tag",
    "review_final_decision",
    "review_final_category",
    "reviewer_notes",
]
HUMAN_OVERRIDE_COLUMNS = [
    "review_final_decision",
    "review_final_category",
    "reviewer_notes",
]
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
    return Path(os.environ.get("BIO_DIGEST_WEB_ROOT", str(SKILL_DIR.parent / "bio-literature-digest-web"))).resolve()


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
        args.summary_config = str(paths.get("summary_config", "") or CANONICAL_PATHS["translation_google_local"])

    if not getattr(args, "smtp_profile", None):
        args.smtp_profile = str(delivery.get("smtp_profile", "") or "primary_smtp")
    if not getattr(args, "timezone", None):
        args.timezone = str(delivery.get("timezone", "") or "Asia/Shanghai")
    if not getattr(args, "delivery_time", None):
        args.delivery_time = str(delivery.get("delivery_time", "") or "08:00")
    if not getattr(args, "allow_review_pending_explicit", False):
        args.allow_review_pending = bool(delivery.get("allow_review_pending", True))

    if not getattr(args, "review_provider", None):
        args.review_provider = str(providers.get("review_provider", "") or "placeholder")
    if not getattr(args, "summary_provider", None):
        args.summary_provider = str(providers.get("summary_provider", "") or "google-basic-v2")

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
    integrations_dir = CANONICAL_PATHS["email_config_local"].parent
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
        google_config = integrations_dir / "translation_google_basic_v2.local.yaml"
        tencent_config = integrations_dir / "translation_tencent_tmt.local.yaml"
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


def review_record_key(row: dict[str, str]) -> tuple[str, str]:
    doi = canonicalize_doi(row.get("doi"))
    if doi:
        return ("doi", doi)
    url = canonicalize_url(row.get("article_url") or row.get("canonical_url"))
    if url:
        return ("url", url)
    return ("title", f"{(row.get('journal') or '').lower()}::{normalize_title(row.get('title_en'))}")


def backlog_record_key(row: dict[str, str]) -> tuple[str, str, str]:
    kind, value = review_record_key(row)
    return (str(row.get("digest_date", "")).strip(), kind, value)


def load_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    return normalize_review_fieldnames(headers, rows)


def normalize_review_fieldnames(headers: list[str], rows: list[dict[str, str]]) -> tuple[list[str], list[dict[str, str]]]:
    if "source_review_csv" not in headers or "source_review_file" in headers:
        return headers, rows

    normalized_headers = ["source_review_file" if header == "source_review_csv" else header for header in headers]
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized = dict(row)
        if "source_review_file" not in normalized and "source_review_csv" in normalized:
            normalized["source_review_file"] = normalized.pop("source_review_csv")
        else:
            normalized.pop("source_review_csv", None)
        normalized_rows.append(normalized)
    return normalized_headers, normalized_rows


def column_index_from_ref(ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", ref.upper())
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - 64)
    return index


def read_xlsx_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("main:si", namespace):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//main:t", namespace)))

        sheet_root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows_by_index: list[dict[int, str]] = []
    for row_node in sheet_root.findall("main:sheetData/main:row", namespace):
        row_values: dict[int, str] = {}
        for cell in row_node.findall("main:c", namespace):
            ref = cell.attrib.get("r", "")
            column_index = column_index_from_ref(ref)
            cell_type = cell.attrib.get("t", "")
            value = ""
            if cell_type == "inlineStr":
                value = "".join(text.text or "" for text in cell.findall("main:is/main:t", namespace))
            else:
                value_node = cell.find("main:v", namespace)
                raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
                if cell_type == "s" and raw_value.isdigit():
                    shared_index = int(raw_value)
                    if 0 <= shared_index < len(shared_strings):
                        value = shared_strings[shared_index]
                else:
                    value = raw_value
            row_values[column_index] = value
        if row_values:
            rows_by_index.append(row_values)

    if not rows_by_index:
        return [], []

    header_map = rows_by_index[0]
    headers = [header_map[index].strip() for index in sorted(header_map) if header_map[index].strip()]
    records: list[dict[str, str]] = []
    for row_map in rows_by_index[1:]:
        record: dict[str, str] = {}
        for index, header in zip(sorted(header_map), headers):
            record[header] = str(row_map.get(index, "") or "")
        records.append(record)
    return headers, records


def load_review_rows(csv_path: Path, xlsx_path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    if xlsx_path.exists():
        try:
            headers, rows = read_xlsx_rows(xlsx_path)
            if headers:
                headers, rows = normalize_review_fieldnames(headers, rows)
                return headers, rows, "xlsx"
        except (KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
            pass
    if csv_path.exists():
        headers, rows = load_csv_rows(csv_path)
        headers, rows = normalize_review_fieldnames(headers, rows)
        return headers, rows, "csv"
    return [], [], "missing"


def load_existing_review_rows(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows: dict[tuple[str, str], dict[str, str]] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[review_record_key(row)] = row
    return rows


def load_archived_backlog_keys(archive_root: Path) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    if not archive_root.exists():
        return keys
    for batch_csv in archive_root.glob("*/*.csv"):
        headers, rows = load_csv_rows(batch_csv)
        if not headers:
            continue
        for row in rows:
            try:
                keys.add(backlog_record_key(row))
            except Exception:
                continue
    return keys


def overlay_editable_columns(row: dict[str, str], existing: dict[str, str]) -> dict[str, str]:
    merged = dict(row)
    for column in EDITABLE_REVIEW_COLUMNS:
        if str(existing.get(column, "")).strip():
            merged[column] = existing[column]
    return merged


def editable_review_hash(row: dict[str, str]) -> str:
    payload = {
        column: str(row.get(column, "")).strip()
        for column in EDITABLE_REVIEW_COLUMNS
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_review_status(row: dict[str, str], baseline_hash: str = "") -> str:
    optimized_at = str(row.get("optimized_at", "")).strip()
    if optimized_at:
        return "optimized"
    current_hash = editable_review_hash(row)
    if baseline_hash and current_hash != baseline_hash:
        return "reviewed_pending_optimization"
    if not baseline_hash and any(str(row.get(column, "")).strip() for column in ("review_final_decision", "review_final_category", "reviewer_notes")):
        return "reviewed_pending_optimization"
    return "pending_review"


def changed_editable_columns(row: dict[str, str], baseline_row: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for column in EDITABLE_REVIEW_COLUMNS:
        if str(row.get(column, "")).strip() != str(baseline_row.get(column, "")).strip():
            changed.append(column)
    return changed


def resolve_admission_tier(
    row: dict[str, str],
    baseline_row: dict[str, str],
    review_status: str,
) -> tuple[str, str]:
    if review_status != "reviewed_pending_optimization":
        return "", ""

    changed_columns = changed_editable_columns(row, baseline_row)
    human_decision = str(row.get("review_final_decision", "")).strip().lower()
    human_category = str(row.get("review_final_category", "")).strip()
    notes = str(row.get("reviewer_notes", "")).strip()
    llm_decision = str(row.get("llm_decision", "")).strip().lower()
    current_category = str(row.get("category", "")).strip()

    interest_only = all(column in {"interest_level", "interest_tag"} for column in changed_columns)
    if interest_only:
        return ("observe", "manual edits only adjust interest fields; do not treat as direct rule evidence")

    if human_decision and human_decision == llm_decision and (not human_category or human_category == current_category):
        return ("apply", "manual override agrees with existing decision/category; low-risk optimization input")

    if human_decision and human_decision in {"keep", "reject"} and llm_decision == "review":
        return ("suggest", "manual decision resolves a review-queue item; use as candidate evidence, not direct truth")

    if human_category and human_category != current_category:
        return ("suggest", "manual category override differs from current category; require Codex validation before applying")

    if any(column in HUMAN_OVERRIDE_COLUMNS for column in changed_columns) or notes:
        return ("suggest", "manual override exists but should be validated by Codex before rule updates")

    return ("observe", "edit is weak or ambiguous; keep for observation only")


def ensure_backlog_review_fields(
    row: dict[str, str],
    archive_date: str,
    source_review_file: Path,
    baseline_row: dict[str, str] | None = None,
    baseline_hash: str = "",
) -> dict[str, str]:
    updated = dict(row)
    updated["digest_date"] = archive_date
    updated["source_review_file"] = str(source_review_file)
    baseline = baseline_row or {}
    previous_hash = str(updated.get("last_manual_edit_hash", "")).strip()
    current_hash = editable_review_hash(updated)
    updated["last_manual_edit_hash"] = current_hash
    updated["review_status"] = resolve_review_status(updated, baseline_hash)
    admission_tier, admission_reason = resolve_admission_tier(updated, baseline, updated["review_status"])
    updated["admission_tier"] = admission_tier
    updated["admission_reason"] = admission_reason
    if updated["review_status"] == "reviewed_pending_optimization" and not str(updated.get("reviewed_at", "")).strip():
        updated["reviewed_at"] = current_timestamp_utc()
    elif updated["review_status"] == "pending_review":
        updated["reviewed_at"] = ""
        updated["admission_tier"] = ""
        updated["admission_reason"] = ""
    if updated["review_status"] != "optimized":
        updated["archived_at"] = ""
    if previous_hash and previous_hash == current_hash and str(updated.get("reviewed_at", "")).strip():
        updated["reviewed_at"] = str(updated.get("reviewed_at", "")).strip()
    return updated


def write_backlog_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_backlog_views(
    backlog_root: Path,
    csv_path: Path,
    html_path: Path,
    xlsx_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]] | None = None,
) -> None:
    loaded_rows = rows
    if loaded_rows is None:
        _, loaded_rows, _ = load_review_rows(csv_path, xlsx_path)
    if loaded_rows is None:
        loaded_rows = []
    if not fieldnames:
        fieldnames = list(loaded_rows[0].keys()) if loaded_rows else []
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from export_digest import (  # type: ignore
        build_review_table_script,
        build_style_override_css,
        render_html_table,
        review_option_map,
        write_csv,
        write_xlsx,
    )
    rules = json.loads(json.dumps(load_yaml_file(CANONICAL_PATHS["rules"]) or {}))
    template_text = CANONICAL_PATHS["email_template"].read_text(encoding="utf-8")
    style_override_css = build_style_override_css(load_yaml_file(CANONICAL_PATHS["email_style_local"]) or {})
    option_map = review_option_map(rules, fieldnames)
    write_csv(csv_path, loaded_rows, fieldnames, option_map)
    write_xlsx(xlsx_path, loaded_rows, fieldnames, option_map)
    html_body = render_html_table(loaded_rows, fieldnames, template_text, style_override_css, rules, "")
    html_body = html_body.replace("</body>", build_review_table_script() + "\n</body>")
    html_path.write_text(html_body, encoding="utf-8")


def sync_review_backlog(args: argparse.Namespace, archive_date: str, target_dir: Path) -> None:
    backlog_root = Path(args.backlog_dir).resolve()
    runtime_defaults = getattr(args, "runtime_defaults", {}) or {}
    runtime_archive_dir = str(runtime_defaults.get("paths", {}).get("archive_dir", "") or "")
    archive_root = Path(str(getattr(args, "archive_dir", "") or runtime_archive_dir or (SKILL_DIR / "archives" / "daily-digests"))).resolve()
    active_csv = backlog_root / "review_backlog.csv"
    active_html = backlog_root / "review_backlog.html"
    active_xlsx = backlog_root / "review_backlog.xlsx"
    active_state = backlog_root / "review_backlog_state.json"
    backlog_archive_root = backlog_root / "archive"
    source_csv = target_dir / "daily_review.csv"
    source_xlsx = target_dir / "daily_review.xlsx"
    if not source_csv.exists() and not source_xlsx.exists():
        return

    source_fields, source_rows, _ = load_review_rows(source_csv, source_xlsx)
    baseline_fields, baseline_rows, _ = load_review_rows(
        archive_root / archive_date / "daily_review.csv",
        archive_root / archive_date / "daily_review.xlsx",
    )
    backlog_fields, backlog_rows, _ = load_review_rows(active_csv, active_xlsx)
    backlog_index = {backlog_record_key(row): dict(row) for row in backlog_rows}
    baseline_index = {review_record_key(row): row for row in baseline_rows}
    archived_keys = load_archived_backlog_keys(backlog_archive_root)

    backlog_prefix = [
        "digest_date",
        "review_status",
        "admission_tier",
        "admission_reason",
        "reviewed_at",
        "optimized_at",
        "archived_at",
        "last_manual_edit_hash",
        "source_review_file",
    ]
    merged_fieldnames = backlog_prefix + [field for field in source_fields if field not in backlog_prefix]

    for row in source_rows:
        key = (archive_date, *review_record_key(row))
        if key in archived_keys and key not in backlog_index:
            continue
        existing = backlog_index.get(key, {})
        merged = overlay_editable_columns(dict(row), existing)
        for metadata_column in ["digest_date", "review_status", "admission_tier", "admission_reason", "reviewed_at", "optimized_at", "archived_at", "last_manual_edit_hash", "source_review_file"]:
            if metadata_column in existing:
                merged[metadata_column] = existing[metadata_column]
        baseline_row = baseline_index.get(review_record_key(row), {})
        merged = ensure_backlog_review_fields(
            merged,
            archive_date,
            source_xlsx if source_xlsx.exists() else source_csv,
            baseline_row,
            editable_review_hash(baseline_row) if baseline_row else "",
        )
        backlog_index[key] = merged

    active_rows: list[dict[str, str]] = []
    archived_rows: list[dict[str, str]] = []
    for row in backlog_index.values():
        normalized = dict(row)
        row_key = backlog_record_key(normalized)
        if row_key in archived_keys and not str(normalized.get("optimized_at", "")).strip():
            continue
        if str(normalized.get("optimized_at", "")).strip():
            normalized["review_status"] = "optimized"
            normalized["admission_tier"] = ""
            normalized["admission_reason"] = "consumed by Codex and archived"
        else:
            normalized["review_status"] = str(normalized.get("review_status", "pending_review")).strip() or "pending_review"
        if normalized["review_status"] == "optimized":
            normalized["archived_at"] = current_timestamp_utc()
            archived_rows.append(normalized)
        else:
            active_rows.append(normalized)

    active_rows.sort(key=lambda item: (item.get("review_status", ""), item.get("digest_date", ""), *review_record_key(item)))
    export_backlog_views(backlog_root, active_csv, active_html, active_xlsx, merged_fieldnames, active_rows)

    state_payload = {
        "updated_at_utc": current_timestamp_utc(),
        "active_backlog_csv": str(active_csv),
        "active_backlog_file": str(active_xlsx),
        "active_counts": {
            "pending_review": sum(1 for row in active_rows if row.get("review_status") == "pending_review"),
            "reviewed_pending_optimization": sum(1 for row in active_rows if row.get("review_status") == "reviewed_pending_optimization"),
            "optimized": 0,
        },
        "admission_counts": {
            "observe": sum(1 for row in active_rows if row.get("admission_tier") == "observe"),
            "suggest": sum(1 for row in active_rows if row.get("admission_tier") == "suggest"),
            "apply": sum(1 for row in active_rows if row.get("admission_tier") == "apply"),
        },
        "archived_today": len(archived_rows),
    }
    active_state.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if archived_rows:
        batch_dir = backlog_archive_root / archive_date
        batch_dir.mkdir(parents=True, exist_ok=True)
        batch_name = datetime.now(ZoneInfo(args.timezone)).strftime("%H%M%S")
        batch_csv = batch_dir / f"optimized_batch_{batch_name}.csv"
        batch_json = batch_dir / f"optimized_batch_{batch_name}.json"
        write_backlog_csv(batch_csv, merged_fieldnames, archived_rows)
        batch_json.write_text(
            json.dumps(
                {
                    "created_at_utc": current_timestamp_utc(),
                    "row_count": len(archived_rows),
                    "source_backlog": str(active_csv),
                    "batch_csv": str(batch_csv),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def sync_review_workspace(args: argparse.Namespace, archive_date: str) -> None:
    work_dir = Path(args.work_dir).resolve()
    review_root = Path(args.review_workspace_dir).resolve()
    target_dir = review_root / archive_date
    target_dir.mkdir(parents=True, exist_ok=True)

    csv_source = work_dir / "daily_review.csv"
    xlsx_source = work_dir / "daily_review.xlsx"
    html_target = target_dir / "daily_review.html"
    csv_target = target_dir / "daily_review.csv"
    xlsx_target = target_dir / "daily_review.xlsx"
    source_fields, source_rows, _ = load_review_rows(csv_source, xlsx_source)
    existing_fields, existing_rows, _ = load_review_rows(csv_target, xlsx_target)
    existing_index = {review_record_key(row): row for row in existing_rows}
    merged_rows = [overlay_editable_columns(dict(row), existing_index.get(review_record_key(row), {})) for row in source_rows]
    export_backlog_views(target_dir, csv_target, html_target, xlsx_target, source_fields or existing_fields, merged_rows)

    manifest = {
        "generated_at_utc": current_timestamp_utc(),
        "source_run_dir": str(work_dir),
        "review_file": str(xlsx_target),
        "review_csv": str(csv_target),
        "review_xlsx": str(xlsx_target),
        "canonical_review_surface": str(Path(args.backlog_dir).resolve() / "review_backlog.xlsx"),
        "derived_review_views": {
            "csv": str(Path(args.backlog_dir).resolve() / "review_backlog.csv"),
            "html": str(Path(args.backlog_dir).resolve() / "review_backlog.html"),
        },
        "editable_columns": EDITABLE_REVIEW_COLUMNS,
        "archive_date": archive_date,
    }
    (target_dir / "review_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sync_review_backlog(args, archive_date, target_dir)


def archive_outputs(args: argparse.Namespace) -> str:
    work_dir = Path(args.work_dir).resolve()
    archive_root = Path(args.archive_dir).resolve()
    archive_date = resolve_archive_date(args)
    target_dir = archive_root / archive_date
    target_dir.mkdir(parents=True, exist_ok=True)

    for filename in [
        "digest.html",
        "digest.csv",
        "digest.xlsx",
        "review_queue.html",
        "review_queue.csv",
        "review_queue.xlsx",
        "daily_review.html",
        "daily_review.csv",
        "daily_review.xlsx",
        "run_metadata.json",
    ]:
        source = work_dir / filename
        if source.exists():
            shutil.copy2(source, target_dir / filename)

    sync_review_workspace(args, archive_date)

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
    return archive_date


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
