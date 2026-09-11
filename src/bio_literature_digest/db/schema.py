#!/usr/bin/env python3
"""Authoritative Producer database schema (baseline 0001).

Single source of truth for the `runs` / `papers` / `paper_records` DDL. Both
`scripts/sync_digest_db.py:ensure_schema` and `migrations/0001_baseline_schema.py`
import from here so the DDL can never drift between the two.

The statements match the live vps219 database exactly (verified read-only on
2026-09-11) — same tables, columns, order, UNIQUE/FK constraints and indexes.
All statements are idempotent (`IF NOT EXISTS`), so re-running against an
existing production database is a structural no-op.
"""
from __future__ import annotations

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        archive_date TEXT NOT NULL,
        status TEXT,
        email_status TEXT,
        window_start_utc TEXT,
        window_end_utc TEXT,
        work_dir TEXT,
        metadata_json TEXT,
        updated_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unique_key TEXT NOT NULL UNIQUE,
        doi_norm TEXT,
        article_url_norm TEXT,
        title_norm TEXT,
        journal_norm TEXT,
        title_en TEXT,
        article_url TEXT,
        doi TEXT,
        journal TEXT,
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        archive_date TEXT NOT NULL,
        dataset TEXT NOT NULL,
        paper_id INTEGER NOT NULL,
        journal TEXT,
        publish_date TEXT,
        category TEXT,
        interest_level TEXT,
        interest_tag TEXT,
        title_en TEXT,
        title_zh TEXT,
        summary_zh TEXT,
        abstract TEXT,
        doi TEXT,
        article_url TEXT,
        tags TEXT,
        llm_decision TEXT,
        review_final_decision TEXT,
        review_final_category TEXT,
        reviewer_notes TEXT,
        row_json TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        UNIQUE(run_id, dataset, paper_id),
        FOREIGN KEY(run_id) REFERENCES runs(run_id),
        FOREIGN KEY(paper_id) REFERENCES papers(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_records_archive_date ON paper_records(archive_date)",
    "CREATE INDEX IF NOT EXISTS idx_records_category ON paper_records(category)",
    "CREATE INDEX IF NOT EXISTS idx_records_dataset ON paper_records(dataset)",
    "CREATE INDEX IF NOT EXISTS idx_runs_archive_date ON runs(archive_date)",
)
