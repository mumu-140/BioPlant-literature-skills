#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from common import canonicalize_doi, canonicalize_url, current_timestamp_utc, normalize_title
except ModuleNotFoundError:
    from scripts.common import canonicalize_doi, canonicalize_url, current_timestamp_utc, normalize_title


DATASET_FILES = {
    "digest": "digest.csv",
    "review_queue": "review_queue.csv",
    "daily_review": "daily_review.csv",
}


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def compute_unique_key(row: dict[str, str]) -> str:
    doi = canonicalize_doi(row.get("doi"))
    if doi:
        return f"doi:{doi}"
    article_url = canonicalize_url(row.get("article_url"))
    if article_url:
        return f"url:{article_url}"
    title = normalize_title(row.get("title_en") or row.get("title_zh"))
    journal = (row.get("journal") or "").strip().lower()
    if title:
        return f"title:{journal}:{title}"
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return "rowhash:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
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
        );

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
        );

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
        );

        CREATE INDEX IF NOT EXISTS idx_runs_archive_date ON runs(archive_date);
        CREATE INDEX IF NOT EXISTS idx_records_archive_date ON paper_records(archive_date);
        CREATE INDEX IF NOT EXISTS idx_records_dataset ON paper_records(dataset);
        CREATE INDEX IF NOT EXISTS idx_records_category ON paper_records(category);
        """
    )


def derive_run_id(run_dir: Path, metadata: dict[str, Any], archive_date: str) -> str:
    started = str(metadata.get("started_at_utc", "") or "")
    if started:
        return f"{archive_date}:{started}"
    payload = f"{archive_date}:{run_dir.resolve()}"
    return "runhash:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def upsert_run(connection: sqlite3.Connection, run_dir: Path, metadata: dict[str, Any], archive_date: str) -> str:
    run_id = derive_run_id(run_dir, metadata, archive_date)
    now = current_timestamp_utc()
    window = metadata.get("window") if isinstance(metadata.get("window"), dict) else {}
    connection.execute(
        """
        INSERT INTO runs (
          run_id, archive_date, status, email_status, window_start_utc, window_end_utc, work_dir, metadata_json, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
          archive_date=excluded.archive_date,
          status=excluded.status,
          email_status=excluded.email_status,
          window_start_utc=excluded.window_start_utc,
          window_end_utc=excluded.window_end_utc,
          work_dir=excluded.work_dir,
          metadata_json=excluded.metadata_json,
          updated_at_utc=excluded.updated_at_utc
        """,
        (
            run_id,
            archive_date,
            str(metadata.get("status", "") or ""),
            str(metadata.get("email_status", "") or ""),
            str(window.get("start_utc", "") or ""),
            str(window.get("end_utc", "") or ""),
            str(run_dir.resolve()),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )
    return run_id


def upsert_paper(connection: sqlite3.Connection, row: dict[str, str]) -> int:
    unique_key = compute_unique_key(row)
    doi_norm = canonicalize_doi(row.get("doi"))
    article_url_norm = canonicalize_url(row.get("article_url"))
    title_norm = normalize_title(row.get("title_en") or row.get("title_zh"))
    journal_norm = (row.get("journal") or "").strip().lower()
    now = current_timestamp_utc()
    connection.execute(
        """
        INSERT INTO papers (
          unique_key, doi_norm, article_url_norm, title_norm, journal_norm, title_en, article_url, doi, journal, created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(unique_key) DO UPDATE SET
          doi_norm=excluded.doi_norm,
          article_url_norm=excluded.article_url_norm,
          title_norm=excluded.title_norm,
          journal_norm=excluded.journal_norm,
          title_en=excluded.title_en,
          article_url=excluded.article_url,
          doi=excluded.doi,
          journal=excluded.journal,
          updated_at_utc=excluded.updated_at_utc
        """,
        (
            unique_key,
            doi_norm,
            article_url_norm,
            title_norm,
            journal_norm,
            row.get("title_en", ""),
            row.get("article_url", ""),
            row.get("doi", ""),
            row.get("journal", ""),
            now,
            now,
        ),
    )
    result = connection.execute("SELECT id FROM papers WHERE unique_key = ?", (unique_key,)).fetchone()
    if not result:
        raise RuntimeError(f"paper upsert failed for key={unique_key}")
    return int(result[0])


def upsert_record(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    archive_date: str,
    dataset: str,
    paper_id: int,
    row: dict[str, str],
) -> None:
    now = current_timestamp_utc()
    connection.execute(
        """
        INSERT INTO paper_records (
          run_id, archive_date, dataset, paper_id, journal, publish_date, category, interest_level, interest_tag,
          title_en, title_zh, summary_zh, abstract, doi, article_url, tags, llm_decision,
          review_final_decision, review_final_category, reviewer_notes, row_json, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, dataset, paper_id) DO UPDATE SET
          archive_date=excluded.archive_date,
          journal=excluded.journal,
          publish_date=excluded.publish_date,
          category=excluded.category,
          interest_level=excluded.interest_level,
          interest_tag=excluded.interest_tag,
          title_en=excluded.title_en,
          title_zh=excluded.title_zh,
          summary_zh=excluded.summary_zh,
          abstract=excluded.abstract,
          doi=excluded.doi,
          article_url=excluded.article_url,
          tags=excluded.tags,
          llm_decision=excluded.llm_decision,
          review_final_decision=excluded.review_final_decision,
          review_final_category=excluded.review_final_category,
          reviewer_notes=excluded.reviewer_notes,
          row_json=excluded.row_json,
          updated_at_utc=excluded.updated_at_utc
        """,
        (
            run_id,
            archive_date,
            dataset,
            paper_id,
            row.get("journal", ""),
            row.get("publish_date", ""),
            row.get("category", ""),
            row.get("interest_level", ""),
            row.get("interest_tag", ""),
            row.get("title_en", ""),
            row.get("title_zh", ""),
            row.get("summary_zh", ""),
            row.get("abstract", ""),
            row.get("doi", ""),
            row.get("article_url", ""),
            row.get("tags", ""),
            row.get("llm_decision", ""),
            row.get("review_final_decision", ""),
            row.get("review_final_category", ""),
            row.get("reviewer_notes", ""),
            json.dumps(row, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )


def sync_database(run_dir: Path, db_path: Path, archive_date: str) -> dict[str, int]:
    run_metadata_path = run_dir / "run_metadata.json"
    metadata: dict[str, Any] = {}
    if run_metadata_path.exists():
        metadata = json.loads(run_metadata_path.read_text(encoding="utf-8"))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    inserted_records = 0
    inserted_papers = 0
    seen_paper_ids: set[int] = set()
    with sqlite3.connect(str(db_path)) as connection:
        ensure_schema(connection)
        run_id = upsert_run(connection, run_dir, metadata, archive_date)
        for dataset, filename in DATASET_FILES.items():
            for row in load_csv_rows(run_dir / filename):
                paper_id = upsert_paper(connection, row)
                upsert_record(
                    connection,
                    run_id=run_id,
                    archive_date=archive_date,
                    dataset=dataset,
                    paper_id=paper_id,
                    row=row,
                )
                inserted_records += 1
                seen_paper_ids.add(paper_id)
        connection.commit()
    inserted_papers = len(seen_paper_ids)
    return {"papers": inserted_papers, "records": inserted_records}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync digest artifacts into a local SQLite database.")
    parser.add_argument("--run-dir", required=True, help="Digest run directory containing CSV artifacts.")
    parser.add_argument("--db-path", required=True, help="SQLite database file path.")
    parser.add_argument("--archive-date", required=True, help="Archive date in YYYY-MM-DD.")
    args = parser.parse_args()

    result = sync_database(Path(args.run_dir).resolve(), Path(args.db_path).resolve(), args.archive_date)
    print(
        f"Synced database at {Path(args.db_path).resolve()}: "
        f"{result['papers']} unique papers, {result['records']} dataset records."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
