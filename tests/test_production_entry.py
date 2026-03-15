#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.run_production_digest import SKILL_DIR, archive_outputs, build_command


class ProductionEntryTest(unittest.TestCase):
    def test_build_command_uses_local_configs_and_schedule_defaults(self) -> None:
        args = argparse.Namespace(
            work_dir="/tmp/prod-run",
            email_config=str(SKILL_DIR / "references" / "email_config.local.yaml"),
            smtp_profile="qq_mail",
            style_config=str(SKILL_DIR / "references" / "email_style.local.yaml"),
            summary_provider=None,
            summary_config=None,
            review_provider="placeholder",
            window_mode="schedule",
            lookback_hours=24,
            window_start=None,
            window_end=None,
            timezone="Asia/Shanghai",
            delivery_time="08:00",
            archive_dir=str(SKILL_DIR / "archives" / "daily-digests"),
            retention_days=30,
            input_file=None,
            manual_review_csv=None,
            allow_review_pending=True,
            skip_email=False,
        )

        command = build_command(args)

        self.assertIn("--email-config", command)
        self.assertIn(str((SKILL_DIR / "references" / "email_config.local.yaml").resolve()), command)
        self.assertIn("--allow-review-pending", command)
        self.assertIn("--summary-provider", command)
        self.assertIn("google-basic-v2", command)
        self.assertIn("--window-mode", command)
        self.assertIn("schedule", command)

    def test_build_command_uses_lookback_hours_only_in_lookback_mode(self) -> None:
        args = argparse.Namespace(
            work_dir="/tmp/prod-run",
            email_config=str(SKILL_DIR / "references" / "email_config.local.yaml"),
            smtp_profile="qq_mail",
            style_config=str(SKILL_DIR / "references" / "email_style.local.yaml"),
            summary_provider="tencent-tmt",
            summary_config=str(SKILL_DIR / "references" / "translation_tencent_tmt.local.yaml"),
            review_provider="placeholder",
            window_mode="lookback",
            lookback_hours=48,
            window_start=None,
            window_end=None,
            timezone="Asia/Shanghai",
            delivery_time="08:00",
            archive_dir=str(SKILL_DIR / "archives" / "daily-digests"),
            retention_days=30,
            input_file=None,
            manual_review_csv=None,
            allow_review_pending=False,
            skip_email=True,
        )

        command = build_command(args)

        self.assertIn("--lookback-hours", command)
        self.assertIn("48", command)
        self.assertIn("--skip-email", command)
        self.assertNotIn("--allow-review-pending", command)

    def test_build_command_passes_explicit_window_through(self) -> None:
        args = argparse.Namespace(
            work_dir="/tmp/prod-run",
            email_config=str(SKILL_DIR / "references" / "email_config.local.yaml"),
            smtp_profile="qq_mail",
            style_config=str(SKILL_DIR / "references" / "email_style.local.yaml"),
            summary_provider="placeholder",
            summary_config=None,
            review_provider="placeholder",
            window_mode="schedule",
            lookback_hours=24,
            window_start="2026-03-13T00:00:00Z",
            window_end="2026-03-15T00:00:00Z",
            timezone="Asia/Shanghai",
            delivery_time="08:00",
            archive_dir=str(SKILL_DIR / "archives" / "daily-digests"),
            retention_days=30,
            input_file=None,
            manual_review_csv=None,
            allow_review_pending=True,
            skip_email=True,
        )

        command = build_command(args)

        self.assertIn("--window-start", command)
        self.assertIn("2026-03-13T00:00:00Z", command)
        self.assertIn("--window-end", command)
        self.assertIn("2026-03-15T00:00:00Z", command)

    def test_archive_outputs_keeps_30_days_and_removes_older(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-archive-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            work_dir = tmpdir_path / "work"
            work_dir.mkdir()
            for filename in ["digest.html", "digest.csv", "digest.xlsx", "review_queue.csv"]:
                (work_dir / filename).write_text(filename, encoding="utf-8")

            archive_dir = tmpdir_path / "archives"
            tz = ZoneInfo("Asia/Shanghai")
            old_date = (datetime.now(tz).date() - timedelta(days=31)).strftime("%Y-%m-%d")
            keep_date = (datetime.now(tz).date() - timedelta(days=29)).strftime("%Y-%m-%d")
            (archive_dir / old_date).mkdir(parents=True)
            (archive_dir / keep_date).mkdir(parents=True)

            args = argparse.Namespace(
                work_dir=str(work_dir),
                archive_dir=str(archive_dir),
                retention_days=30,
                timezone="Asia/Shanghai",
                window_end="2026-03-15T00:00:00Z",
            )

            archive_outputs(args)

            archived_dir = archive_dir / "2026-03-15"
            self.assertTrue((archived_dir / "digest.csv").exists())
            self.assertTrue((archived_dir / "digest.xlsx").exists())
            self.assertFalse((archive_dir / old_date).exists())
            self.assertTrue((archive_dir / keep_date).exists())


if __name__ == "__main__":
    unittest.main()
