#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_DB_TARGET = SKILL_DIR / "var" / "db" / "bio_digest.sqlite3"
DEFAULT_WORK_DIR = "${SKILL_DIR}/var/work/current"

LEGACY_TO_STAGE1_PATHS = {
    "${SKILL_DIR}/.env.local": "${SKILL_DIR}/local/.env.local",
    "${SKILL_DIR}/archives/daily-digests": "${SKILL_DIR}/var/archives/daily-digests",
    "${SKILL_DIR}/reviews/daily-reviews": "${SKILL_DIR}/var/reviews/daily-reviews",
    "${SKILL_DIR}/reviews/backlog": "${SKILL_DIR}/var/reviews/backlog",
    "${SKILL_DIR}/logs/launchd/bio-digest-daily.stdout.log": "${SKILL_DIR}/var/logs/launchd/bio-digest-daily.stdout.log",
    "${SKILL_DIR}/logs/launchd/bio-digest-daily.stderr.log": "${SKILL_DIR}/var/logs/launchd/bio-digest-daily.stderr.log",
    "${SKILL_DIR}/config/integrations/email_config.local.yaml": "${SKILL_DIR}/local/integrations/email_config.yaml",
    "${SKILL_DIR}/config/integrations/users.local.yaml": "${SKILL_DIR}/local/integrations/users.yaml",
    "${SKILL_DIR}/config/integrations/email_style.local.yaml": "${SKILL_DIR}/local/integrations/email_style.yaml",
    "${SKILL_DIR}/config/integrations/translation_google_basic_v2.local.yaml": "${SKILL_DIR}/local/integrations/translation_google_basic_v2.yaml",
    "${SKILL_DIR}/config/integrations/translation_tencent_tmt.local.yaml": "${SKILL_DIR}/local/integrations/translation_tencent_tmt.yaml",
    "${SKILL_DIR}/bio-literature-config/data/shared/bio_digest.sqlite3": "${SKILL_DIR}/var/db/bio_digest.sqlite3",
}


@dataclass
class MoveOperation:
    source: Path
    target: Path
    kind: str


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def expand_path(raw: str) -> Path:
    expanded = raw.replace("${SKILL_DIR}", str(SKILL_DIR)).replace("${HOME}", str(Path.home()))
    return Path(expanded).expanduser()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(payload, dict):
        return payload
    return {}


def legacy_db_paths() -> set[Path]:
    return {
        expand_path(raw).resolve()
        for raw in LEGACY_TO_STAGE1_PATHS
        if "bio_digest.sqlite3" in raw
    }


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_database_target() -> Path:
    runtime_candidates = [
        SKILL_DIR / "local" / "runtime" / "production.yaml",
        SKILL_DIR / "config" / "runtime" / "production.local.yaml",
    ]
    for runtime_path in runtime_candidates:
        runtime = load_yaml(runtime_path)
        database = runtime.get("database")
        if not isinstance(database, dict):
            continue
        sqlite_path = str(database.get("sqlite_path", "") or "").strip()
        if not sqlite_path:
            continue
        resolved = expand_path(sqlite_path)
        if not resolved.is_absolute():
            resolved = (SKILL_DIR / resolved).resolve()
        resolved = resolved.resolve()
        if resolved in legacy_db_paths():
            return DEFAULT_DB_TARGET
        return resolved
    return DEFAULT_DB_TARGET


def remap_legacy_path(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return value
    if value in LEGACY_TO_STAGE1_PATHS:
        return LEGACY_TO_STAGE1_PATHS[value]
    resolved = expand_path(value)
    if not resolved.is_absolute():
        resolved = (SKILL_DIR / resolved).resolve()
    resolved = resolved.resolve()
    for legacy_raw, stage1_raw in LEGACY_TO_STAGE1_PATHS.items():
        if resolved == expand_path(legacy_raw).resolve():
            return stage1_raw
    return value


def normalize_runtime_override(runtime_path: Path) -> list[str]:
    payload = load_yaml(runtime_path)
    if not payload:
        return []

    changed_fields: list[str] = []

    environment = payload.get("environment")
    if isinstance(environment, dict):
        env_file = str(environment.get("env_file", "") or "").strip()
        mapped = remap_legacy_path(env_file)
        if mapped != env_file:
            environment["env_file"] = mapped
            changed_fields.append("environment.env_file")

    paths = payload.get("paths")
    if isinstance(paths, dict):
        work_dir = str(paths.get("work_dir", "") or "").strip()
        if not work_dir:
            paths["work_dir"] = DEFAULT_WORK_DIR
            changed_fields.append("paths.work_dir")
        else:
            resolved_work_dir = expand_path(work_dir)
            if not resolved_work_dir.is_absolute():
                resolved_work_dir = (SKILL_DIR / resolved_work_dir).resolve()
            if not is_within(resolved_work_dir.resolve(), SKILL_DIR / "var"):
                paths["work_dir"] = DEFAULT_WORK_DIR
                changed_fields.append("paths.work_dir")

        for key in [
            "archive_dir",
            "review_workspace_dir",
            "backlog_dir",
            "email_config",
            "users_config",
            "style_config",
            "summary_config",
        ]:
            current_value = str(paths.get(key, "") or "").strip()
            mapped = remap_legacy_path(current_value)
            if mapped != current_value:
                paths[key] = mapped
                changed_fields.append(f"paths.{key}")

    database = payload.get("database")
    if isinstance(database, dict):
        sqlite_path = str(database.get("sqlite_path", "") or "").strip()
        mapped = remap_legacy_path(sqlite_path)
        if mapped != sqlite_path:
            database["sqlite_path"] = mapped
            changed_fields.append("database.sqlite_path")

    scheduler = payload.get("scheduler")
    if isinstance(scheduler, dict):
        launchd = scheduler.get("launchd")
        if isinstance(launchd, dict):
            for key in ["stdout_log", "stderr_log"]:
                current_value = str(launchd.get(key, "") or "").strip()
                mapped = remap_legacy_path(current_value)
                if mapped != current_value:
                    launchd[key] = mapped
                    changed_fields.append(f"scheduler.launchd.{key}")

    if changed_fields:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return changed_fields


def build_operations() -> list[MoveOperation]:
    operations: list[MoveOperation] = [
        MoveOperation(SKILL_DIR / "archives", SKILL_DIR / "var" / "archives", "dir"),
        MoveOperation(SKILL_DIR / "reviews", SKILL_DIR / "var" / "reviews", "dir"),
        MoveOperation(SKILL_DIR / "logs", SKILL_DIR / "var" / "logs", "dir"),
        MoveOperation(SKILL_DIR / ".env.local", SKILL_DIR / "local" / ".env.local", "file"),
        MoveOperation(
            SKILL_DIR / "config" / "runtime" / "production.local.yaml",
            SKILL_DIR / "local" / "runtime" / "production.yaml",
            "file",
        ),
    ]

    legacy_integrations_dir = SKILL_DIR / "config" / "integrations"
    for source in sorted(legacy_integrations_dir.glob("*.local.yaml")):
        target_name = source.name.replace(".local.yaml", ".yaml")
        operations.append(
            MoveOperation(source, SKILL_DIR / "local" / "integrations" / target_name, "file")
        )

    legacy_db = SKILL_DIR / "bio-literature-config" / "data" / "shared" / "bio_digest.sqlite3"
    operations.append(MoveOperation(legacy_db, resolve_database_target(), "file"))
    return operations


def detect_conflicts(operations: list[MoveOperation]) -> list[str]:
    conflicts: list[str] = []
    for op in operations:
        if not op.source.exists():
            continue
        if op.source.resolve() == op.target.resolve():
            continue
        if op.target.exists():
            conflicts.append(f"target already exists: {op.target} (source: {op.source})")
    return conflicts


def print_plan(operations: list[MoveOperation]) -> None:
    print("# Runtime Layout Migration Plan")
    for op in operations:
        if op.source.exists():
            print(f"MOVE {op.source} -> {op.target}")
        else:
            print(f"SKIP (missing) {op.source} -> {op.target}")


def write_manifest(
    operations: list[MoveOperation],
    moved: list[MoveOperation],
    runtime_updates: list[str],
    cleanup_removed: list[str],
) -> Path:
    manifests_dir = SKILL_DIR / "var" / "migrations" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"runtime-layout-migration-{utc_timestamp()}.json"
    moved_set = {(op.source, op.target) for op in moved}
    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "skill_dir": str(SKILL_DIR),
        "operations": [
            {
                "source": str(op.source),
                "target": str(op.target),
                "kind": op.kind,
                "status": "moved" if (op.source, op.target) in moved_set else "skipped_missing",
            }
            for op in operations
        ],
        "rollback_moves": [
            {"source": str(op.target), "target": str(op.source), "kind": op.kind}
            for op in reversed(moved)
        ],
        "runtime_override_updates": runtime_updates,
        "cleanup_removed": cleanup_removed,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def apply_moves(operations: list[MoveOperation]) -> list[MoveOperation]:
    moved: list[MoveOperation] = []
    for op in operations:
        if not op.source.exists():
            continue
        if op.source.resolve() == op.target.resolve():
            continue
        op.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(op.source), str(op.target))
        moved.append(op)
    return moved


def cleanup_legacy_layout() -> list[str]:
    removed_entries: list[str] = []
    legacy_root = SKILL_DIR / "bio-literature-config"
    if not legacy_root.exists():
        return removed_entries

    for path in legacy_root.rglob(".DS_Store"):
        path.unlink(missing_ok=True)
        removed_entries.append(str(path))

    for directory in sorted((path for path in legacy_root.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
            removed_entries.append(str(directory))
        except OSError:
            continue
    try:
        legacy_root.rmdir()
        removed_entries.append(str(legacy_root))
    except OSError as exc:
        raise SystemExit(
            f"migration aborted: legacy directory still contains unmanaged files: {legacy_root}"
        ) from exc
    return removed_entries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-shot migration to Stage 1 runtime layout (local/ + var/)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print planned moves.")
    args = parser.parse_args()

    operations = build_operations()
    print_plan(operations)

    conflicts = detect_conflicts(operations)
    if conflicts:
        print("\n# Conflicts")
        for issue in conflicts:
            print(f"- {issue}")
        raise SystemExit("migration aborted due to conflicts")

    if args.dry_run:
        print("\nDry-run complete. No files were changed.")
        return 0

    moved = apply_moves(operations)
    runtime_updates = normalize_runtime_override(SKILL_DIR / "local" / "runtime" / "production.yaml")
    cleanup_removed = cleanup_legacy_layout()
    manifest_path = write_manifest(operations, moved, runtime_updates, cleanup_removed)

    print("\n# Migration Result")
    print(f"Moved entries: {len(moved)}")
    if runtime_updates:
        print(f"Updated runtime override fields: {', '.join(runtime_updates)}")
    if cleanup_removed:
        print(f"Removed legacy entries: {len(cleanup_removed)}")
    print(f"Backup manifest: {manifest_path}")
    print("Rollback moves are recorded in the manifest under `rollback_moves`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
