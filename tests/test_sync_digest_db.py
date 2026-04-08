#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.sync_digest_db import sync_database


class SyncDigestDbTest(unittest.TestCase):
    def test_sync_database_is_idempotent_and_structured(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-db-sync-") as tmpdir:
            root = Path(tmpdir)
            run_dir = root / "run"
            run_dir.mkdir(parents=True, exist_ok=True)
            db_path = root / "digest.sqlite3"

            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "status": "success",
                        "email_status": "sent",
                        "started_at_utc": "2026-04-08T00:00:00Z",
                        "window": {
                            "start_utc": "2026-04-07T16:00:00Z",
                            "end_utc": "2026-04-08T00:00:00Z",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "digest.csv").write_text(
                "\n".join(
                    [
                        "journal,publish_date,category,interest_level,interest_tag,title_en,title_zh,summary_zh,abstract,doi,article_url,tags",
                        "Nature,2026-04-08,omics,感兴趣,组学,Paper A,论文A,摘要A,Abstract A,10.1000/a,https://example.com/a,tag-a",
                        "Cell,2026-04-08,genomics,一般,基因研究,Paper B,论文B,摘要B,Abstract B,10.1000/b,https://example.com/b,tag-b",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "review_queue.csv").write_text(
                "\n".join(
                    [
                        "journal,publish_date,category,interest_level,interest_tag,title_en,title_zh,summary_zh,abstract,doi,article_url,tags,llm_decision",
                        "Nature,2026-04-08,omics,感兴趣,组学,Paper A,论文A,摘要A,Abstract A,10.1000/a,https://example.com/a,tag-a,review",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "daily_review.csv").write_text(
                "\n".join(
                    [
                        "journal,publish_date,category,interest_level,interest_tag,title_en,title_zh,summary_zh,abstract,doi,article_url,tags,review_final_decision,review_final_category,reviewer_notes",
                        "Nature,2026-04-08,omics,非常感兴趣,组学,Paper A,论文A,摘要A,Abstract A,10.1000/a,https://example.com/a,tag-a,keep,omics,good",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            first = sync_database(run_dir, db_path, "2026-04-08")
            second = sync_database(run_dir, db_path, "2026-04-08")
            self.assertEqual(first["papers"], 2)
            self.assertEqual(second["papers"], 2)

            with sqlite3.connect(str(db_path)) as connection:
                run_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                paper_count = connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
                record_count = connection.execute("SELECT COUNT(*) FROM paper_records").fetchone()[0]
                daily_records = connection.execute(
                    "SELECT COUNT(*) FROM paper_records WHERE dataset = 'daily_review'"
                ).fetchone()[0]
                self.assertEqual(run_count, 1)
                self.assertEqual(paper_count, 2)
                self.assertEqual(record_count, 4)
                self.assertEqual(daily_records, 1)


if __name__ == "__main__":
    unittest.main()
