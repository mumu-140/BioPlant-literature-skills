#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from project_layout import SKILL_DIR
except ModuleNotFoundError:
    from scripts.project_layout import SKILL_DIR

SRC_DIR = SKILL_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bio_literature_digest.review.backlog import (  # noqa: E402
    DEFAULT_BACKLOG_DIR,
    export_backlog_views,
    load_review_rows,
    review_record_key,
    write_backlog_csv,
)

try:
    from common import current_timestamp_utc
except ModuleNotFoundError:
    from scripts.common import current_timestamp_utc


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark reviewed backlog rows as optimized after Codex consumes them.")
    parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    parser.add_argument("--all-reviewed-pending", action="store_true")
    parser.add_argument("--selection-json")
    parser.add_argument("--digest-date", default="")
    args = parser.parse_args()

    selection_json = Path(args.selection_json).resolve() if args.selection_json else None
    if not args.all_reviewed_pending and not selection_json:
        raise SystemExit("Pass --selection-json for selective marking, or --all-reviewed-pending for a bulk mark.")

    result = mark_optimized(
        Path(args.backlog_dir).resolve(),
        all_reviewed_pending=bool(args.all_reviewed_pending),
        selection_json=selection_json,
        digest_date=str(args.digest_date).strip(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
