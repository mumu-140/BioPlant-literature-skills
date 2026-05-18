#!/usr/bin/env python3
"""Unified review backlog management CLI.

Combines three former standalone scripts:
  finalize_review_backlog.py  -> subcommand: finalize
  mark_review_backlog_optimized.py  -> subcommand: mark
  refresh_review_backlog.py    -> subcommand: refresh

Usage:
    python review_backlog.py finalize [--backlog-dir DIR] [--timezone TZ]
    python review_backlog.py mark [--backlog-dir DIR] (--all-reviewed-pending | --selection-json FILE) [--digest-date DATE]
    python review_backlog.py refresh [--review-workspace-dir DIR] [--backlog-dir DIR] [--archive-dir DIR] [--timezone TZ]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from scripts._bootstrap import DEFAULT_RUNTIME_CONFIG_PATH, load_runtime_config
except ModuleNotFoundError:
    from _bootstrap import DEFAULT_RUNTIME_CONFIG_PATH, load_runtime_config

try:
    from scripts.common import current_timestamp_utc
except ModuleNotFoundError:
    from common import current_timestamp_utc

from bio_literature_digest.review.backlog import (  # noqa: E402
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_BACKLOG_DIR,
    DEFAULT_REVIEW_WORKSPACE_DIR,
    export_backlog_views,
    load_review_rows,
    review_record_key,
    sync_review_backlog,
    write_backlog_csv,
)


RUNTIME_DEFAULTS = load_runtime_config(DEFAULT_RUNTIME_CONFIG_PATH)
DEFAULT_TIMEZONE = str(RUNTIME_DEFAULTS.get("delivery", {}).get("timezone", "Asia/Shanghai"))


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------

def finalize_backlog(backlog_dir: Path, timezone_name: str) -> dict[str, object]:
    active_csv = backlog_dir / "review_backlog.csv"
    active_html = backlog_dir / "review_backlog.html"
    active_xlsx = backlog_dir / "review_backlog.xlsx"
    active_state = backlog_dir / "review_backlog_state.json"
    selection_json = backlog_dir / "optimization_selection.json"
    archive_root = backlog_dir / "archive"

    fieldnames, rows, _ = load_review_rows(active_csv, active_xlsx)
    active_rows: list[dict[str, str]] = []
    archived_rows: list[dict[str, str]] = []
    archived_digest_dates: set[str] = set()

    for row in rows:
        normalized = dict(row)
        optimized_at = str(normalized.get("optimized_at", "")).strip()
        review_status = str(normalized.get("review_status", "")).strip()
        if review_status == "optimized" or optimized_at:
            normalized["review_status"] = "optimized"
            normalized["optimized_at"] = optimized_at or current_timestamp_utc()
            normalized["archived_at"] = current_timestamp_utc()
            archived_rows.append(normalized)
            if normalized.get("digest_date"):
                archived_digest_dates.add(str(normalized["digest_date"]))
        else:
            active_rows.append(normalized)

    write_backlog_csv(active_csv, fieldnames, active_rows)
    export_backlog_views(backlog_dir, active_csv, active_html, active_xlsx, fieldnames, active_rows)

    batches: list[str] = []
    archived_selection = ""
    if archived_rows:
        batch_dir_name = max(archived_digest_dates) if archived_digest_dates else current_timestamp_utc()[:10]
        batch_dir = archive_root / batch_dir_name
        batch_dir.mkdir(parents=True, exist_ok=True)
        batch_name = current_timestamp_utc().replace(":", "").replace("-", "").replace("T", "-").replace("Z", "")
        batch_csv = batch_dir / f"optimized_batch_{batch_name}.csv"
        batch_json = batch_dir / f"optimized_batch_{batch_name}.json"
        batch_selection = batch_dir / f"optimized_batch_{batch_name}.selection.json"
        write_backlog_csv(batch_csv, fieldnames, archived_rows)
        if selection_json.exists():
            shutil.copy2(selection_json, batch_selection)
            archived_selection = str(batch_selection)
            selection_json.unlink()
        batch_json.write_text(
            json.dumps(
                {
                    "created_at_utc": current_timestamp_utc(),
                    "row_count": len(archived_rows),
                    "source_backlog": str(active_csv),
                    "batch_csv": str(batch_csv),
                    "selection_json": archived_selection,
                    "timezone": timezone_name,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        batches.append(str(batch_csv))

    state_payload = {
        "updated_at_utc": current_timestamp_utc(),
        "active_backlog_csv": str(active_csv),
        "active_backlog_file": str(active_xlsx),
        "active_counts": {
            "pending_review": sum(1 for row in active_rows if row.get("review_status") == "pending_review"),
            "reviewed_pending_optimization": sum(
                1 for row in active_rows if row.get("review_status") == "reviewed_pending_optimization"
            ),
            "optimized": 0,
        },
        "admission_counts": {
            "observe": sum(1 for row in active_rows if row.get("admission_tier") == "observe"),
            "suggest": sum(1 for row in active_rows if row.get("admission_tier") == "suggest"),
            "apply": sum(1 for row in active_rows if row.get("admission_tier") == "apply"),
        },
        "archived_now": len(archived_rows),
        "archive_batches": batches,
        "archived_selection_json": archived_selection,
    }
    active_state.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state_payload


# ---------------------------------------------------------------------------
# mark
# ---------------------------------------------------------------------------

def mark_optimized(
    backlog_dir: Path,
    *,
    all_reviewed_pending: bool,
    selection_json: Path | None = None,
    digest_date: str = "",
) -> dict[str, object]:
    active_csv = backlog_dir / "review_backlog.csv"
    active_html = backlog_dir / "review_backlog.html"
    active_xlsx = backlog_dir / "review_backlog.xlsx"
    fieldnames, rows, _ = load_review_rows(active_csv, active_xlsx)
    if not fieldnames:
        raise SystemExit(f"Backlog file is empty or missing headers: {active_xlsx if active_xlsx.exists() else active_csv}")

    selection_keys: set[tuple[str, str, str]] = set()
    if selection_json:
        raw = json.loads(selection_json.read_text(encoding="utf-8"))
        entries = raw.get("selected_rows", raw) if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            raise SystemExit(f"Invalid selection JSON format: {selection_json}")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            digest = str(entry.get("digest_date", "")).strip()
            key_kind = str(entry.get("key_kind", "")).strip()
            key_value = str(entry.get("key_value", "")).strip()
            if digest and key_kind and key_value:
                selection_keys.add((digest, key_kind, key_value))
        if not selection_keys:
            raise SystemExit(f"Selection JSON does not contain any valid selected_rows entries: {selection_json}")

    marked = 0
    timestamp = current_timestamp_utc()
    updated_rows: list[dict[str, str]] = []
    for row in rows:
        normalized = dict(row)
        row_key = (str(normalized.get("digest_date", "")).strip(), *review_record_key(normalized))
        should_mark = False
        if selection_keys:
            should_mark = row_key in selection_keys
        elif all_reviewed_pending and normalized.get("review_status") == "reviewed_pending_optimization":
            should_mark = True

        if should_mark:
            if digest_date and normalized.get("digest_date") != digest_date:
                updated_rows.append(normalized)
                continue
            if normalized.get("review_status") != "reviewed_pending_optimization":
                updated_rows.append(normalized)
                continue
            normalized["review_status"] = "optimized"
            normalized["optimized_at"] = timestamp
            marked += 1
        updated_rows.append(normalized)

    write_backlog_csv(active_csv, fieldnames, updated_rows)
    export_backlog_views(backlog_dir, active_csv, active_html, active_xlsx, fieldnames, updated_rows)
    return {
        "updated_at_utc": timestamp,
        "backlog_file": str(active_xlsx if active_xlsx.exists() else active_csv),
        "marked_rows": marked,
        "all_reviewed_pending": all_reviewed_pending,
        "selection_json": str(selection_json) if selection_json else "",
        "digest_date": digest_date,
    }


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

def refresh_backlog(
    review_workspace_dir: Path, backlog_dir: Path, archive_dir: Path, timezone_name: str
) -> dict[str, object]:
    processed_dates: list[str] = []
    args = argparse.Namespace(backlog_dir=str(backlog_dir), archive_dir=str(archive_dir), timezone=timezone_name)
    if review_workspace_dir.exists():
        for date_dir in sorted(review_workspace_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            if not (date_dir / "daily_review.xlsx").exists() and not (date_dir / "daily_review.csv").exists():
                continue
            sync_review_backlog(args, date_dir.name, date_dir)
            processed_dates.append(date_dir.name)
    result = {
        "updated_at_utc": current_timestamp_utc(),
        "review_workspace_dir": str(review_workspace_dir),
        "backlog_dir": str(backlog_dir),
        "archive_dir": str(archive_dir),
        "processed_dates": processed_dates,
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review backlog management — finalize / mark / refresh."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # finalize
    f_parser = sub.add_parser("finalize", help="Archive optimized backlog rows and rebuild CSV/HTML/XLSX views.")
    f_parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    f_parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)

    # mark
    m_parser = sub.add_parser("mark", help="Mark reviewed backlog rows as 'optimized'.")
    m_parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    m_parser.add_argument("--all-reviewed-pending", action="store_true")
    m_parser.add_argument("--selection-json")
    m_parser.add_argument("--digest-date", default="")

    # refresh
    r_parser = sub.add_parser("refresh", help="Sync daily review workspace snapshots into the backlog.")
    r_parser.add_argument("--review-workspace-dir", default=str(DEFAULT_REVIEW_WORKSPACE_DIR))
    r_parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    r_parser.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    r_parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "finalize":
        backlog_dir = Path(args.backlog_dir).resolve()
        if not backlog_dir.exists():
            raise SystemExit(f"Backlog directory does not exist: {backlog_dir}")
        result = finalize_backlog(backlog_dir, args.timezone)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "mark":
        if not args.all_reviewed_pending and not args.selection_json:
            raise SystemExit("Pass --selection-json for selective marking, or --all-reviewed-pending for bulk mark.")
        selection_json = Path(args.selection_json).resolve() if args.selection_json else None
        result = mark_optimized(
            Path(args.backlog_dir).resolve(),
            all_reviewed_pending=bool(args.all_reviewed_pending),
            selection_json=selection_json,
            digest_date=str(args.digest_date).strip(),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "refresh":
        result = refresh_backlog(
            Path(args.review_workspace_dir).resolve(),
            Path(args.backlog_dir).resolve(),
            Path(args.archive_dir).resolve(),
            args.timezone,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())