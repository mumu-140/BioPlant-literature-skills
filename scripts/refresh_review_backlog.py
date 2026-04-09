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
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_BACKLOG_DIR,
    DEFAULT_REVIEW_WORKSPACE_DIR,
    sync_review_backlog,
)

try:
    from common import current_timestamp_utc
except ModuleNotFoundError:
    from scripts.common import current_timestamp_utc
try:
    from project_layout import DEFAULT_RUNTIME_CONFIG_PATH, load_runtime_config
except ModuleNotFoundError:
    from scripts.project_layout import DEFAULT_RUNTIME_CONFIG_PATH, load_runtime_config


RUNTIME_DEFAULTS = load_runtime_config(DEFAULT_RUNTIME_CONFIG_PATH)
DEFAULT_TIMEZONE = str(RUNTIME_DEFAULTS.get("delivery", {}).get("timezone", "Asia/Shanghai"))


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
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
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
