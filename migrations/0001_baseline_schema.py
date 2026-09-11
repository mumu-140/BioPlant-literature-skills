#!/usr/bin/env python3
"""Baseline schema migration 0001 — freeze the production `papers` database.

Target environment: vps219 only (Producer repo). The database file is passed
explicitly via `--db-path` and resolved at runtime — never guessed.

The DDL lives in `src/bio_literature_digest/db/schema.py` (single source of
truth); this migration applies it and is the standard schema-evolution entry
point going forward (`migrations/0002_*.py`, ...). It performs **no structural
change** to an existing database — every statement is `IF NOT EXISTS` and the
DDL was verified against the live vps219 database on 2026-09-11.

Rollback: no-op — the migration only creates objects production already
possesses; `git revert` of this file is the complete rollback.

Usage (on vps219, never locally):

    # standalone, against a database file
    python3 migrations/0001_baseline_schema.py --db-path var/db/bio_digest.sqlite3

or implicitly, via the existing sync path:

    python3 scripts/sync_digest_db.py --run-dir ... --db-path ... --archive-date ...
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parents[1]
_SRC_DIR = _SKILL_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from bio_literature_digest.db.schema import SCHEMA_STATEMENTS  # noqa: E402


def apply_baseline(connection: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply baseline schema migration 0001 to a Producer SQLite database.")
    parser.add_argument("--db-path", required=True, help="Path to the Producer SQLite database file.")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    connection = sqlite3.connect(str(db_path))
    try:
        apply_baseline(connection)
        print(f"Baseline migration 0001 applied to {db_path}")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
