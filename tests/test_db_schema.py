#!/usr/bin/env python3
"""Schema tests: ensure_schema (sync path) and migration 0001 share one DDL.

The two entry points must produce byte-identical schema objects; any drift
between them is a bug because production DBs are built through both paths.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402,F401  (puts src/ on sys.path)
from bio_literature_digest.db.schema import SCHEMA_STATEMENTS  # noqa: E402
import sync_digest_db  # noqa: E402
import importlib.util  # noqa: E402

_MIGRATION_PATH = SKILL_DIR / "migrations" / "0001_baseline_schema.py"
_spec = importlib.util.spec_from_file_location("migration_0001_baseline_schema", _MIGRATION_PATH)
migration_0001 = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(migration_0001)


def dump_schema(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "select type, name, tbl_name, sql from sqlite_master where sql is not null order by type, name"
    ).fetchall()
    return "\n".join(f"{t}|{n}|{tbl}|{sql.strip()}" for t, n, tbl, sql in rows)


class BaselineSchemaTest(unittest.TestCase):
    def test_ensure_schema_and_migration_0001_produce_identical_schema(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-schema-") as tmpdir:
            sync_db = Path(tmpdir) / "sync.sqlite3"
            migration_db = Path(tmpdir) / "migration.sqlite3"

            sync_connection = sqlite3.connect(str(sync_db))
            try:
                sync_digest_db.ensure_schema(sync_connection)
            finally:
                sync_connection.close()

            migration_connection = sqlite3.connect(str(migration_db))
            try:
                migration_0001.apply_baseline(migration_connection)
            finally:
                migration_connection.close()

            with sqlite3.connect(str(sync_db)) as a, sqlite3.connect(str(migration_db)) as b:
                self.assertEqual(dump_schema(a), dump_schema(b))

    def test_migration_0001_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-schema-") as tmpdir:
            db_path = Path(tmpdir) / "migration.sqlite3"
            connection = sqlite3.connect(str(db_path))
            try:
                migration_0001.apply_baseline(connection)
                migration_0001.apply_baseline(connection)
                tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
            finally:
                connection.close()
            # sqlite_sequence is auto-created by AUTOINCREMENT.
            self.assertEqual({"runs", "papers", "paper_records", "sqlite_sequence"}, tables)

    def test_schema_statements_are_all_idempotent(self) -> None:
        for statement in SCHEMA_STATEMENTS:
            self.assertIn("IF NOT EXISTS", statement)


if __name__ == "__main__":
    unittest.main()
