#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_production_digest import export_backlog_views, write_backlog_csv


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"


class ReviewBacklogFlowTest(unittest.TestCase):
    def test_refresh_backlog_promotes_manually_edited_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-backlog-refresh-") as tmpdir:
            root = Path(tmpdir)
            archive_dir = root / "archives" / "daily-digests" / "2026-03-17"
            review_dir = root / "reviews" / "daily-reviews" / "2026-03-17"
            backlog_dir = root / "reviews" / "backlog"
            archive_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)

            fieldnames = [
                "source_id",
                "journal",
                "publish_date",
                "publication_stage",
                "category",
                "interest_level",
                "interest_level_options",
                "interest_tag",
                "interest_tag_options",
                "title_en",
                "title_zh",
                "summary_zh",
                "abstract",
                "doi",
                "article_url",
                "tags",
                "llm_decision",
                "llm_confidence",
                "llm_reason",
                "review_final_decision",
                "review_final_decision_options",
                "review_final_category",
                "review_final_category_options",
                "reviewer_notes",
            ]
            baseline_row = {
                "source_id": "nature",
                "journal": "Nature",
                "publish_date": "2026-03-16T00:00:00Z",
                "publication_stage": "journal",
                "category": "plant-biology",
                "interest_level": "非常感兴趣",
                "interest_level_options": "仅保留 | 非常一般 | 一般 | 感兴趣 | 非常感兴趣",
                "interest_tag": "生物通络",
                "interest_tag_options": "生物学工具技术 | 模型 | 生物设计 | 组学 | 基因研究 | 蛋白研究 | 生物通络 | 其他",
                "title_en": "Paper",
                "title_zh": "论文",
                "summary_zh": "摘要",
                "abstract": "abstract",
                "doi": "10.1000/example",
                "article_url": "https://example.org/paper",
                "tags": "plant",
                "llm_decision": "keep",
                "llm_confidence": "0.9",
                "llm_reason": "ok",
                "review_final_decision": "",
                "review_final_decision_options": "keep | review | reject",
                "review_final_category": "",
                "review_final_category_options": "plant-biology | other",
                "reviewer_notes": "",
            }
            edited_row = dict(baseline_row)
            edited_row["review_final_decision"] = "keep"
            edited_row["reviewer_notes"] = "human reviewed"

            for target_dir, row in [(archive_dir, baseline_row), (review_dir, edited_row)]:
                with (target_dir / "daily_review.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow(row)
                export_backlog_views(
                    target_dir,
                    target_dir / "daily_review.csv",
                    target_dir / "daily_review.html",
                    target_dir / "daily_review.xlsx",
                    fieldnames,
                    [row],
                )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "refresh_review_backlog.py"),
                    "--review-workspace-dir",
                    str(root / "reviews" / "daily-reviews"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--archive-dir",
                    str(root / "archives" / "daily-digests"),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )

            with (backlog_dir / "review_backlog.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["review_status"], "reviewed_pending_optimization")
            self.assertEqual(rows[0]["review_final_decision"], "keep")
            self.assertEqual(rows[0]["admission_tier"], "apply")

    def test_refresh_backlog_assigns_observe_for_interest_only_edits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-backlog-observe-") as tmpdir:
            root = Path(tmpdir)
            archive_dir = root / "archives" / "daily-digests" / "2026-03-17"
            review_dir = root / "reviews" / "daily-reviews" / "2026-03-17"
            backlog_dir = root / "reviews" / "backlog"
            archive_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)

            fieldnames = [
                "source_id", "journal", "publish_date", "publication_stage", "category",
                "interest_level", "interest_level_options", "interest_tag", "interest_tag_options",
                "title_en", "title_zh", "summary_zh", "abstract", "doi", "article_url", "tags",
                "llm_decision", "llm_confidence", "llm_reason", "review_final_decision",
                "review_final_decision_options", "review_final_category", "review_final_category_options", "reviewer_notes",
            ]
            baseline_row = {
                "source_id": "science",
                "journal": "Science",
                "publish_date": "2026-03-16T00:00:00Z",
                "publication_stage": "journal",
                "category": "omics",
                "interest_level": "感兴趣",
                "interest_level_options": "仅保留 | 非常一般 | 一般 | 感兴趣 | 非常感兴趣",
                "interest_tag": "组学",
                "interest_tag_options": "生物学工具技术 | 模型 | 生物设计 | 组学 | 基因研究 | 蛋白研究 | 生物通络 | 其他",
                "title_en": "Interest only",
                "title_zh": "仅兴趣修改",
                "summary_zh": "摘要",
                "abstract": "abstract",
                "doi": "10.1000/observe",
                "article_url": "https://example.org/observe",
                "tags": "omics",
                "llm_decision": "keep",
                "llm_confidence": "0.9",
                "llm_reason": "ok",
                "review_final_decision": "",
                "review_final_decision_options": "keep | review | reject",
                "review_final_category": "",
                "review_final_category_options": "omics | other",
                "reviewer_notes": "",
            }
            edited_row = dict(baseline_row)
            edited_row["interest_level"] = "非常感兴趣"

            for target_dir, row in [(archive_dir, baseline_row), (review_dir, edited_row)]:
                with (target_dir / "daily_review.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow(row)
                export_backlog_views(
                    target_dir,
                    target_dir / "daily_review.csv",
                    target_dir / "daily_review.html",
                    target_dir / "daily_review.xlsx",
                    fieldnames,
                    [row],
                )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "refresh_review_backlog.py"),
                    "--review-workspace-dir",
                    str(root / "reviews" / "daily-reviews"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--archive-dir",
                    str(root / "archives" / "daily-digests"),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )

            with (backlog_dir / "review_backlog.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["review_status"], "reviewed_pending_optimization")
            self.assertEqual(rows[0]["admission_tier"], "observe")

    def test_mark_and_finalize_backlog_completes_consumed_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-backlog-mark-") as tmpdir:
            backlog_dir = Path(tmpdir) / "backlog"
            backlog_dir.mkdir(parents=True)
            csv_path = backlog_dir / "review_backlog.csv"
            html_path = backlog_dir / "review_backlog.html"
            xlsx_path = backlog_dir / "review_backlog.xlsx"
            state_path = backlog_dir / "review_backlog_state.json"

            fieldnames = [
                "digest_date",
                "review_status",
                "reviewed_at",
                "optimized_at",
                "archived_at",
                "last_manual_edit_hash",
                "source_review_file",
                "source_id",
                "journal",
                "publish_date",
                "publication_stage",
                "category",
                "interest_level",
                "interest_level_options",
                "interest_tag",
                "interest_tag_options",
                "title_en",
                "title_zh",
                "summary_zh",
                "abstract",
                "doi",
                "article_url",
                "tags",
                "llm_decision",
                "llm_confidence",
                "llm_reason",
                "review_final_decision",
                "review_final_decision_options",
                "review_final_category",
                "review_final_category_options",
                "reviewer_notes",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "digest_date": "2026-03-17",
                        "review_status": "reviewed_pending_optimization",
                        "reviewed_at": "2026-03-17T09:00:00Z",
                        "source_review_file": str(
                            SKILL_DIR / "var" / "reviews" / "daily-reviews" / "2026-03-17" / "daily_review.xlsx"
                        ),
                        "source_id": "nature",
                        "journal": "Nature",
                        "publication_stage": "journal",
                        "category": "plant-biology",
                        "interest_level": "非常感兴趣",
                        "interest_tag": "生物通络",
                        "title_en": "Reviewed row",
                    }
                )
            html_path.write_text("placeholder", encoding="utf-8")
            xlsx_path.write_bytes(b"placeholder")
            state_path.write_text("{}", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "mark_review_backlog_optimized.py"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--all-reviewed-pending",
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "finalize_review_backlog.py"),
                    "--backlog-dir",
                    str(backlog_dir),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows, [])
            archive_root = backlog_dir / "archive" / "2026-03-17"
            self.assertTrue(any(archive_root.glob("optimized_batch_*.csv")))

    def test_mark_selection_only_consumes_selected_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-backlog-selective-") as tmpdir:
            backlog_dir = Path(tmpdir) / "backlog"
            backlog_dir.mkdir(parents=True)
            selection_path = backlog_dir / "optimization_selection.json"
            fieldnames = [
                "digest_date",
                "review_status",
                "admission_tier",
                "admission_reason",
                "reviewed_at",
                "optimized_at",
                "archived_at",
                "last_manual_edit_hash",
                "source_review_file",
                "source_id",
                "journal",
                "publish_date",
                "publication_stage",
                "category",
                "interest_level",
                "interest_tag",
                "title_en",
                "title_zh",
                "summary_zh",
                "abstract",
                "doi",
                "article_url",
                "tags",
                "llm_decision",
                "llm_confidence",
                "llm_reason",
                "review_final_decision",
                "review_final_category",
                "reviewer_notes",
            ]
            rows = [
                {
                    "digest_date": "2026-03-17",
                    "review_status": "reviewed_pending_optimization",
                    "admission_tier": "apply",
                    "reviewed_at": "2026-03-17T09:00:00Z",
                    "source_review_file": str(
                        SKILL_DIR / "var" / "reviews" / "daily-reviews" / "2026-03-17" / "daily_review.xlsx"
                    ),
                    "source_id": "nature",
                    "journal": "Nature",
                    "publication_stage": "journal",
                    "category": "plant-biology",
                    "interest_level": "非常感兴趣",
                    "interest_tag": "生物通络",
                    "title_en": "Consumed row",
                    "doi": "10.1000/consumed",
                    "llm_decision": "keep",
                    "review_final_decision": "keep",
                },
                {
                    "digest_date": "2026-03-17",
                    "review_status": "reviewed_pending_optimization",
                    "admission_tier": "suggest",
                    "reviewed_at": "2026-03-17T09:05:00Z",
                    "source_review_file": str(
                        SKILL_DIR / "var" / "reviews" / "daily-reviews" / "2026-03-17" / "daily_review.xlsx"
                    ),
                    "source_id": "science",
                    "journal": "Science",
                    "publication_stage": "journal",
                    "category": "omics",
                    "interest_level": "感兴趣",
                    "interest_tag": "组学",
                    "title_en": "Deferred row",
                    "doi": "10.1000/deferred",
                    "llm_decision": "keep",
                    "review_final_decision": "reject",
                },
            ]
            write_backlog_csv(backlog_dir / "review_backlog.csv", fieldnames, rows)
            export_backlog_views(
                backlog_dir,
                backlog_dir / "review_backlog.csv",
                backlog_dir / "review_backlog.html",
                backlog_dir / "review_backlog.xlsx",
                fieldnames,
                rows,
            )
            selection_path.write_text(
                json.dumps(
                    {
                        "selected_rows": [
                            {
                                "digest_date": "2026-03-17",
                                "key_kind": "doi",
                                "key_value": "10.1000/consumed",
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "mark_review_backlog_optimized.py"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--selection-json",
                    str(selection_path),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "finalize_review_backlog.py"),
                    "--backlog-dir",
                    str(backlog_dir),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )

            with (backlog_dir / "review_backlog.csv").open("r", encoding="utf-8", newline="") as handle:
                active_rows = list(csv.DictReader(handle))
            self.assertEqual(len(active_rows), 1)
            self.assertEqual(active_rows[0]["title_en"], "Deferred row")
            self.assertEqual(active_rows[0]["review_status"], "reviewed_pending_optimization")
            archive_root = backlog_dir / "archive" / "2026-03-17"
            archived_rows: list[dict[str, str]] = []
            for batch_csv in archive_root.glob("optimized_batch_*.csv"):
                with batch_csv.open("r", encoding="utf-8", newline="") as handle:
                    archived_rows.extend(list(csv.DictReader(handle)))
            self.assertEqual(len(archived_rows), 1)
            self.assertEqual(archived_rows[0]["title_en"], "Consumed row")

    def test_refresh_does_not_rehydrate_archived_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-backlog-no-rehydrate-") as tmpdir:
            root = Path(tmpdir)
            archive_dir = root / "archives" / "daily-digests" / "2026-03-17"
            review_dir = root / "reviews" / "daily-reviews" / "2026-03-17"
            backlog_dir = root / "reviews" / "backlog"
            archive_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)
            backlog_dir.mkdir(parents=True)

            fieldnames = [
                "source_id",
                "journal",
                "publish_date",
                "publication_stage",
                "category",
                "interest_level",
                "interest_level_options",
                "interest_tag",
                "interest_tag_options",
                "title_en",
                "title_zh",
                "summary_zh",
                "abstract",
                "doi",
                "article_url",
                "tags",
                "llm_decision",
                "llm_confidence",
                "llm_reason",
                "review_final_decision",
                "review_final_decision_options",
                "review_final_category",
                "review_final_category_options",
                "reviewer_notes",
            ]
            baseline_row = {
                "source_id": "nature",
                "journal": "Nature",
                "publish_date": "2026-03-16T00:00:00Z",
                "publication_stage": "journal",
                "category": "plant-biology",
                "interest_level": "感兴趣",
                "interest_level_options": "仅保留 | 非常一般 | 一般 | 感兴趣 | 非常感兴趣",
                "interest_tag": "生物通络",
                "interest_tag_options": "生物学工具技术 | 模型 | 生物设计 | 组学 | 基因研究 | 蛋白研究 | 生物通络 | 其他",
                "title_en": "Archived once",
                "title_zh": "已消费一次",
                "summary_zh": "摘要",
                "abstract": "abstract",
                "doi": "10.1000/archived-once",
                "article_url": "https://example.org/archived-once",
                "tags": "plant",
                "llm_decision": "keep",
                "llm_confidence": "0.9",
                "llm_reason": "ok",
                "review_final_decision": "",
                "review_final_decision_options": "keep | review | reject",
                "review_final_category": "",
                "review_final_category_options": "plant-biology | other",
                "reviewer_notes": "",
            }
            review_row = dict(baseline_row)
            review_row["review_final_decision"] = "keep"
            for target_dir, row in [(archive_dir, baseline_row), (review_dir, review_row)]:
                with (target_dir / "daily_review.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow(row)
                export_backlog_views(
                    target_dir,
                    target_dir / "daily_review.csv",
                    target_dir / "daily_review.html",
                    target_dir / "daily_review.xlsx",
                    fieldnames,
                    [row],
                )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "refresh_review_backlog.py"),
                    "--review-workspace-dir",
                    str(root / "reviews" / "daily-reviews"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--archive-dir",
                    str(root / "archives" / "daily-digests"),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )
            selection_path = backlog_dir / "optimization_selection.json"
            selection_path.write_text(
                json.dumps(
                    {
                        "selected_rows": [
                            {"digest_date": "2026-03-17", "key_kind": "doi", "key_value": "10.1000/archived-once"}
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "mark_review_backlog_optimized.py"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--selection-json",
                    str(selection_path),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "finalize_review_backlog.py"),
                    "--backlog-dir",
                    str(backlog_dir),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "refresh_review_backlog.py"),
                    "--review-workspace-dir",
                    str(root / "reviews" / "daily-reviews"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--archive-dir",
                    str(root / "archives" / "daily-digests"),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )

            with (backlog_dir / "review_backlog.csv").open("r", encoding="utf-8", newline="") as handle:
                active_rows = list(csv.DictReader(handle))
            self.assertEqual(active_rows, [])

    def test_refresh_backlog_keeps_existing_backlog_xlsx_edits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-backlog-preserve-") as tmpdir:
            root = Path(tmpdir)
            archive_dir = root / "archives" / "daily-digests" / "2026-03-17"
            review_dir = root / "reviews" / "daily-reviews" / "2026-03-17"
            backlog_dir = root / "reviews" / "backlog"
            archive_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)
            backlog_dir.mkdir(parents=True)

            fieldnames = [
                "digest_date",
                "review_status",
                "admission_tier",
                "admission_reason",
                "reviewed_at",
                "optimized_at",
                "archived_at",
                "last_manual_edit_hash",
                "source_review_file",
                "source_id",
                "journal",
                "publish_date",
                "publication_stage",
                "category",
                "interest_level",
                "interest_tag",
                "title_en",
                "title_zh",
                "summary_zh",
                "abstract",
                "doi",
                "article_url",
                "tags",
                "llm_decision",
                "llm_confidence",
                "llm_reason",
                "review_final_decision",
                "review_final_category",
                "reviewer_notes",
            ]

            baseline_row = {
                "source_id": "nature",
                "journal": "Nature",
                "publish_date": "2026-03-16T00:00:00Z",
                "publication_stage": "journal",
                "category": "plant-biology",
                "interest_level": "感兴趣",
                "interest_tag": "生物通络",
                "title_en": "Backlog preserve",
                "title_zh": "保留 backlog 编辑",
                "summary_zh": "摘要",
                "abstract": "abstract",
                "doi": "10.1000/preserve",
                "article_url": "https://example.org/preserve",
                "tags": "plant",
                "llm_decision": "keep",
                "llm_confidence": "0.9",
                "llm_reason": "ok",
                "review_final_decision": "",
                "review_final_category": "",
                "reviewer_notes": "",
            }
            with (archive_dir / "daily_review.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(baseline_row.keys()))
                writer.writeheader()
                writer.writerow(baseline_row)
            export_backlog_views(
                archive_dir,
                archive_dir / "daily_review.csv",
                archive_dir / "daily_review.html",
                archive_dir / "daily_review.xlsx",
                list(baseline_row.keys()),
                [baseline_row],
            )

            review_row = dict(baseline_row)
            review_row["review_final_decision"] = "keep"
            with (review_dir / "daily_review.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(review_row.keys()))
                writer.writeheader()
                writer.writerow(review_row)
            export_backlog_views(
                review_dir,
                review_dir / "daily_review.csv",
                review_dir / "daily_review.html",
                review_dir / "daily_review.xlsx",
                list(review_row.keys()),
                [review_row],
            )

            backlog_row = {
                "digest_date": "2026-03-17",
                "review_status": "reviewed_pending_optimization",
                "admission_tier": "suggest",
                "admission_reason": "manual override exists but should be validated by Codex before rule updates",
                "reviewed_at": "2026-03-17T09:00:00Z",
                "optimized_at": "",
                "archived_at": "",
                "last_manual_edit_hash": "",
                "source_review_file": str(review_dir / "daily_review.xlsx"),
                **review_row,
            }
            backlog_row["reviewer_notes"] = "keep my backlog edit"
            backlog_row["review_final_category"] = "other"
            write_backlog_csv(backlog_dir / "review_backlog.csv", fieldnames, [backlog_row])
            export_backlog_views(
                backlog_dir,
                backlog_dir / "review_backlog.csv",
                backlog_dir / "review_backlog.html",
                backlog_dir / "review_backlog.xlsx",
                fieldnames,
                [backlog_row],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "refresh_review_backlog.py"),
                    "--review-workspace-dir",
                    str(root / "reviews" / "daily-reviews"),
                    "--backlog-dir",
                    str(backlog_dir),
                    "--archive-dir",
                    str(root / "archives" / "daily-digests"),
                ],
                check=True,
                cwd=SKILL_DIR,
                env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            )

            with (backlog_dir / "review_backlog.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["reviewer_notes"], "keep my backlog edit")
            self.assertEqual(rows[0]["review_final_category"], "other")


if __name__ == "__main__":
    unittest.main()
