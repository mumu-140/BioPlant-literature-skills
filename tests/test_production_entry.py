#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.project_layout import canonical_paths
from scripts import run_production_digest
from scripts.run_production_digest import (
    RUN_LOCK_FILENAME,
    SKILL_DIR,
    acquire_run_lock,
    archive_outputs,
    build_command,
    release_run_lock,
    should_archive_failed_run,
)


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_raw.jsonl"
CANONICAL_PATHS = canonical_paths()


class ProductionEntryTest(unittest.TestCase):
    def test_acquire_run_lock_rejects_active_pid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-lock-active-") as tmpdir:
            work_dir = Path(tmpdir)
            lock_path = work_dir / RUN_LOCK_FILENAME
            lock_path.write_text(
                json.dumps({"pid": os.getpid(), "started_at_utc": "2026-04-08T00:00:00Z"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                acquire_run_lock(work_dir, stale_hours=12)

    def test_acquire_run_lock_reclaims_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-lock-stale-") as tmpdir:
            work_dir = Path(tmpdir)
            lock_path = work_dir / RUN_LOCK_FILENAME
            lock_path.write_text(
                json.dumps({"pid": 999999, "started_at_utc": "2026-04-01T00:00:00Z"}, ensure_ascii=False),
                encoding="utf-8",
            )
            stale_time = datetime.now().timestamp() - 7200
            os.utime(lock_path, (stale_time, stale_time))

            acquired = acquire_run_lock(work_dir, stale_hours=1)
            payload = json.loads(acquired.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            release_run_lock(acquired)
            self.assertFalse(acquired.exists())

    def test_build_command_uses_local_configs_and_schedule_defaults(self) -> None:
        args = argparse.Namespace(
            work_dir="/tmp/prod-run",
            email_config=str(CANONICAL_PATHS["email_config_local"]),
            smtp_profile="primary_smtp",
            style_config=str(CANONICAL_PATHS["email_style_local"]),
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
            review_workspace_dir=str(SKILL_DIR / "reviews" / "daily-reviews"),
            backlog_dir=str(SKILL_DIR / "reviews" / "backlog"),
            retention_days=30,
            input_file=None,
            manual_review_csv=None,
            allow_review_pending=True,
            skip_email=False,
        )

        command = build_command(args)

        self.assertIn("--email-config", command)
        self.assertIn(str(CANONICAL_PATHS["email_config_local"].resolve()), command)
        self.assertIn("--allow-review-pending", command)
        self.assertIn("--summary-provider", command)
        self.assertIn("google-basic-v2", command)
        self.assertIn("--window-mode", command)
        self.assertIn("schedule", command)

    def test_build_command_uses_lookback_hours_only_in_lookback_mode(self) -> None:
        args = argparse.Namespace(
            work_dir="/tmp/prod-run",
            email_config=str(CANONICAL_PATHS["email_config_local"]),
            smtp_profile="primary_smtp",
            style_config=str(CANONICAL_PATHS["email_style_local"]),
            summary_provider="tencent-tmt",
            summary_config=str(CANONICAL_PATHS["translation_tencent_local"]),
            review_provider="placeholder",
            window_mode="lookback",
            lookback_hours=48,
            window_start=None,
            window_end=None,
            timezone="Asia/Shanghai",
            delivery_time="08:00",
            archive_dir=str(SKILL_DIR / "archives" / "daily-digests"),
            review_workspace_dir=str(SKILL_DIR / "reviews" / "daily-reviews"),
            backlog_dir=str(SKILL_DIR / "reviews" / "backlog"),
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
            email_config=str(CANONICAL_PATHS["email_config_local"]),
            smtp_profile="primary_smtp",
            style_config=str(CANONICAL_PATHS["email_style_local"]),
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
            review_workspace_dir=str(SKILL_DIR / "reviews" / "daily-reviews"),
            backlog_dir=str(SKILL_DIR / "reviews" / "backlog"),
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
                (work_dir / filename).write_text(filename, encoding="utf-8")

            archive_dir = tmpdir_path / "archives"
            review_workspace_dir = tmpdir_path / "reviews"
            backlog_dir = tmpdir_path / "backlog"
            tz = ZoneInfo("Asia/Shanghai")
            old_date = (datetime.now(tz).date() - timedelta(days=31)).strftime("%Y-%m-%d")
            keep_date = (datetime.now(tz).date() - timedelta(days=29)).strftime("%Y-%m-%d")
            (archive_dir / old_date).mkdir(parents=True)
            (archive_dir / keep_date).mkdir(parents=True)

            args = argparse.Namespace(
                work_dir=str(work_dir),
                archive_dir=str(archive_dir),
                review_workspace_dir=str(review_workspace_dir),
                backlog_dir=str(backlog_dir),
                retention_days=30,
                timezone="Asia/Shanghai",
                window_end="2026-03-15T00:00:00Z",
            )

            archive_outputs(args)

            archived_dir = archive_dir / "2026-03-15"
            self.assertTrue((archived_dir / "digest.csv").exists())
            self.assertTrue((archived_dir / "digest.xlsx").exists())
            self.assertTrue((archived_dir / "review_queue.xlsx").exists())
            self.assertTrue((archived_dir / "daily_review.csv").exists())
            self.assertTrue((archived_dir / "run_metadata.json").exists())
            self.assertTrue((review_workspace_dir / "2026-03-15" / "daily_review.csv").exists())
            self.assertTrue((review_workspace_dir / "2026-03-15" / "review_manifest.json").exists())
            manifest = json.loads((review_workspace_dir / "2026-03-15" / "review_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["review_file"].endswith("/daily_review.xlsx"))
            self.assertTrue(manifest["canonical_review_surface"].endswith("/review_backlog.xlsx"))
            self.assertTrue((backlog_dir / "review_backlog.csv").exists())
            self.assertTrue((backlog_dir / "review_backlog.xlsx").exists())
            self.assertTrue((backlog_dir / "review_backlog.html").exists())
            self.assertTrue((backlog_dir / "review_backlog_state.json").exists())
            self.assertFalse((archive_dir / old_date).exists())
            self.assertTrue((archive_dir / keep_date).exists())

    def test_should_archive_failed_run_only_for_send_email_failures_with_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-failed-archive-") as tmpdir:
            work_dir = Path(tmpdir)
            metadata = {
                "status": "failed",
                "failed_step": "send_email",
            }
            (work_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            for filename in [
                "digest.html",
                "digest.csv",
                "digest.xlsx",
                "daily_review.xlsx",
            ]:
                (work_dir / filename).write_text("ok", encoding="utf-8")

            self.assertTrue(should_archive_failed_run(work_dir))

            metadata["failed_step"] = "translate_and_summarize"
            (work_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            self.assertFalse(should_archive_failed_run(work_dir))

    def test_main_archives_outputs_after_send_email_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-prod-main-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            work_dir = tmpdir_path / "work"
            archive_dir = tmpdir_path / "archive"
            review_workspace_dir = tmpdir_path / "reviews"
            backlog_dir = tmpdir_path / "backlog"
            env_file = tmpdir_path / ".env.local"
            env_file.write_text("", encoding="utf-8")
            work_dir.mkdir()
            metadata = {
                "status": "failed",
                "failed_step": "send_email",
                "window": {
                    "start_utc": "2026-04-06T16:00:00Z",
                    "end_utc": "2026-04-08T00:00:00Z",
                },
            }
            (work_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            (work_dir / "digest.html").write_text("digest", encoding="utf-8")
            (work_dir / "digest.csv").write_text("title_en\npaper\n", encoding="utf-8")
            (work_dir / "digest.xlsx").write_text("xlsx", encoding="utf-8")
            (work_dir / "review_queue.html").write_text("queue", encoding="utf-8")
            (work_dir / "review_queue.csv").write_text("title_en\n", encoding="utf-8")
            (work_dir / "review_queue.xlsx").write_text("xlsx", encoding="utf-8")
            (work_dir / "daily_review.html").write_text("daily", encoding="utf-8")
            (work_dir / "daily_review.csv").write_text("title_en,doi,article_url,journal\npaper,10.1/test,https://example.com,J\n", encoding="utf-8")
            (work_dir / "daily_review.xlsx").write_text("xlsx", encoding="utf-8")

            argv = [
                "run_production_digest.py",
                "--env-file",
                str(env_file),
                "--work-dir",
                str(work_dir),
                "--archive-dir",
                str(archive_dir),
                "--review-workspace-dir",
                str(review_workspace_dir),
                "--backlog-dir",
                str(backlog_dir),
                "--window-start",
                "2026-04-06T16:00:00Z",
                "--window-end",
                "2026-04-08T00:00:00Z",
                "--skip-email",
            ]

            with patch.object(sys, "argv", argv):
                with patch.object(run_production_digest, "load_env_file") as load_env_mock:
                    with patch.object(run_production_digest, "build_command", return_value=["python3", "fake"]):
                        with patch.object(
                            run_production_digest.subprocess,
                            "run",
                            return_value=subprocess.CompletedProcess(["python3", "fake"], 1),
                        ):
                            exit_code = run_production_digest.main()

            self.assertEqual(exit_code, 1)
            load_env_mock.assert_called_once()
            archived_dir = archive_dir / "2026-04-08"
            self.assertTrue((archived_dir / "run_metadata.json").exists())
            self.assertTrue((archived_dir / "digest.csv").exists())
            self.assertTrue((review_workspace_dir / "2026-04-08" / "review_manifest.json").exists())

    def test_run_production_digest_smoke_succeeds_without_web_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-prod-smoke-") as tmpdir:
            root = Path(tmpdir)
            work_dir = root / "work"
            archive_dir = root / "archive"
            review_workspace_dir = root / "reviews"
            backlog_dir = root / "backlog"
            env_file = root / ".env.local"
            env_file.write_text("", encoding="utf-8")

            command = [
                sys.executable,
                str(SKILL_DIR / "scripts" / "run_production_digest.py"),
                "--env-file",
                str(env_file),
                "--work-dir",
                str(work_dir),
                "--archive-dir",
                str(archive_dir),
                "--review-workspace-dir",
                str(review_workspace_dir),
                "--backlog-dir",
                str(backlog_dir),
                "--input-file",
                str(FIXTURE_PATH),
                "--skip-email",
                "--summary-provider",
                "placeholder",
                "--review-provider",
                "placeholder",
                "--window-start",
                "2026-03-13T00:00:00Z",
                "--window-end",
                "2026-03-15T00:00:00Z",
                "--web-project-root",
                str(root / "missing-web-project"),
            ]

            completed = subprocess.run(command, check=True, cwd=SKILL_DIR, capture_output=True, text=True)

            self.assertIn("[production] running stable digest entrypoint", completed.stdout)
            archived_dir = archive_dir / "2026-03-15"
            self.assertTrue((archived_dir / "run_metadata.json").exists())
            self.assertTrue((archived_dir / "digest.csv").exists())
            self.assertTrue((review_workspace_dir / "2026-03-15" / "review_manifest.json").exists())
            self.assertTrue((backlog_dir / "review_backlog.xlsx").exists())
            metadata = json.loads((archived_dir / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "success")
            self.assertEqual(metadata["email_status"], "skipped")
            self.assertEqual(metadata["window"]["start_utc"], "2026-03-13T00:00:00Z")
            self.assertEqual(metadata["window"]["end_utc"], "2026-03-15T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
