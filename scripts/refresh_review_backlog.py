#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from run_production_digest import DEFAULT_REVIEW_WORKSPACE_DIR, DEFAULT_BACKLOG_DIR, DEFAULT_ARCHIVE_DIR, sync_review_backlog
except ModuleNotFoundError:
    from scripts.run_production_digest import DEFAULT_REVIEW_WORKSPACE_DIR, DEFAULT_BACKLOG_DIR, DEFAULT_ARCHIVE_DIR, sync_review_backlog

try:
    from common import current_timestamp_utc
except ModuleNotFoundError:
    from scripts.common import current_timestamp_utc


def refresh_backlog(review_workspace_dir: Path, backlog_dir: Path, archive_dir: Path, timezone_name: str) -> dict[str, object]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh active review backlog from daily review workspace snapshots.")
    parser.add_argument("--review-workspace-dir", default=str(DEFAULT_REVIEW_WORKSPACE_DIR))
    parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    parser.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()

    result = refresh_backlog(
        Path(args.review_workspace_dir).resolve(),
        Path(args.backlog_dir).resolve(),
        Path(args.archive_dir).resolve(),
        args.timezone,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
