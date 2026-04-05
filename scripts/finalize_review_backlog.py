#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

try:
    from run_production_digest import (
        DEFAULT_BACKLOG_DIR,
        export_backlog_views,
        load_review_rows,
        write_backlog_csv,
    )
except ModuleNotFoundError:
    from scripts.run_production_digest import (
        DEFAULT_BACKLOG_DIR,
        export_backlog_views,
        load_review_rows,
        write_backlog_csv,
    )

try:
    from common import current_timestamp_utc
except ModuleNotFoundError:
    from scripts.common import current_timestamp_utc


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive optimized review backlog rows and rebuild active backlog views.")
    parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()

    backlog_dir = Path(args.backlog_dir).resolve()
    if not backlog_dir.exists():
        raise SystemExit(f"Backlog directory does not exist: {backlog_dir}")
    result = finalize_backlog(backlog_dir, args.timezone)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
