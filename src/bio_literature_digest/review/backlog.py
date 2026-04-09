from __future__ import annotations

import csv
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from bio_literature_digest.config.runtime import SKILL_DIR, canonical_paths, load_runtime_config


SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common import canonicalize_doi, canonicalize_url, current_timestamp_utc, load_yaml_file, normalize_title  # noqa: E402
from export_digest import (  # noqa: E402
    build_review_table_script,
    build_style_override_css,
    render_html_table,
    review_option_map,
    write_csv,
    write_xlsx,
)


CANONICAL_PATHS = canonical_paths()
RUNTIME_DEFAULTS = load_runtime_config()
DEFAULT_ARCHIVE_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("archive_dir", SKILL_DIR / "var" / "archives" / "daily-digests")))
DEFAULT_REVIEW_WORKSPACE_DIR = Path(
    str(RUNTIME_DEFAULTS.get("paths", {}).get("review_workspace_dir", SKILL_DIR / "var" / "reviews" / "daily-reviews"))
)
DEFAULT_BACKLOG_DIR = Path(str(RUNTIME_DEFAULTS.get("paths", {}).get("backlog_dir", SKILL_DIR / "var" / "reviews" / "backlog")))
DEFAULT_TIMEZONE = str(RUNTIME_DEFAULTS.get("delivery", {}).get("timezone", "Asia/Shanghai"))
EDITABLE_REVIEW_COLUMNS = [
    "interest_level",
    "interest_tag",
    "review_final_decision",
    "review_final_category",
    "reviewer_notes",
]
HUMAN_OVERRIDE_COLUMNS = [
    "review_final_decision",
    "review_final_category",
    "reviewer_notes",
]


def first_existing_path(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_archive_date(args: Any) -> str:
    window_end = str(getattr(args, "window_end", "") or "").strip()
    if window_end:
        try:
            end_dt = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
            return end_dt.astimezone(ZoneInfo(args.timezone)).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.now(ZoneInfo(args.timezone)).strftime("%Y-%m-%d")


def review_record_key(row: dict[str, str]) -> tuple[str, str]:
    doi = canonicalize_doi(row.get("doi"))
    if doi:
        return ("doi", doi)
    article_url = canonicalize_url(row.get("article_url") or row.get("canonical_url"))
    if article_url:
        return ("url", article_url)
    return ("title", f"{(row.get('journal') or '').lower()}::{normalize_title(row.get('title_en'))}")


def backlog_record_key(row: dict[str, str]) -> tuple[str, str, str]:
    digest_date = str(row.get("digest_date", "")).strip()
    key_kind, key_value = review_record_key(row)
    return (digest_date, key_kind, key_value)


def load_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [{key: str(value or "") for key, value in row.items()} for row in reader]
    return fieldnames, rows


def normalize_review_fieldnames(headers: list[str], rows: list[dict[str, str]]) -> tuple[list[str], list[dict[str, str]]]:
    normalized_headers = list(headers)
    for column in EDITABLE_REVIEW_COLUMNS:
        if column not in normalized_headers:
            normalized_headers.append(column)
    for metadata_column in [
        "digest_date",
        "review_status",
        "admission_tier",
        "admission_reason",
        "reviewed_at",
        "optimized_at",
        "archived_at",
        "last_manual_edit_hash",
        "source_review_file",
    ]:
        if metadata_column not in normalized_headers:
            normalized_headers.append(metadata_column)
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized = {key: str(value or "") for key, value in row.items()}
        for column in normalized_headers:
            normalized.setdefault(column, "")
        normalized_rows.append(normalized)
    return normalized_headers, normalized_rows


def column_index_from_ref(ref: str) -> int:
    current = 0
    for char in ref:
        if not char.isalpha():
            break
        current = current * 26 + (ord(char.upper()) - 64)
    return max(current - 1, 0)


def read_xlsx_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("rb") as handle:
        archive = ElementTree  # silence import grouping

    with zipfile.ZipFile(path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        sheets = workbook.find("main:sheets", namespace)
        if sheets is None:
            return [], []
        first_sheet = sheets.find("main:sheet", namespace)
        if first_sheet is None:
            return [], []
        workbook_rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_namespace = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
        sheet_rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not sheet_rel_id:
            return [], []
        target_path = ""
        for rel in workbook_rels.findall("rel:Relationship", rel_namespace):
            if rel.attrib.get("Id") == sheet_rel_id:
                target_path = rel.attrib.get("Target", "")
                break
        if not target_path:
            return [], []
        worksheet_xml = archive.read(f"xl/{target_path}")
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                texts = [
                    node.text or ""
                    for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                ]
                shared_strings.append("".join(texts))

    root = ElementTree.fromstring(worksheet_xml)
    rows_xml = root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row")
    parsed_rows: list[list[str]] = []
    for row_xml in rows_xml:
        values: list[str] = []
        current_index = 0
        for cell in row_xml.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
            ref = cell.attrib.get("r", "")
            target_index = column_index_from_ref(ref)
            while current_index < target_index:
                values.append("")
                current_index += 1
            value = ""
            value_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
            if value_node is not None and value_node.text is not None:
                raw_value = value_node.text
                if cell.attrib.get("t") == "s":
                    try:
                        value = shared_strings[int(raw_value)]
                    except (ValueError, IndexError):
                        value = raw_value
                else:
                    value = raw_value
            is_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
            if is_node is not None:
                texts = [
                    node.text or ""
                    for node in is_node.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                ]
                value = "".join(texts)
            values.append(value)
            current_index += 1
        parsed_rows.append(values)
    if not parsed_rows:
        return [], []
    headers = [str(value or "").strip() for value in parsed_rows[0]]
    rows: list[dict[str, str]] = []
    for raw_row in parsed_rows[1:]:
        row_map = {
            headers[index]: str(raw_row[index] or "") if index < len(raw_row) else ""
            for index in range(len(headers))
            if headers[index]
        }
        if any(str(value or "").strip() for value in row_map.values()):
            rows.append(row_map)
    return normalize_review_fieldnames(headers, rows)


def load_review_rows(csv_path: Path, xlsx_path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    if xlsx_path.exists():
        try:
            fields, rows = read_xlsx_rows(xlsx_path)
            if fields:
                return fields, rows, "xlsx"
        except (KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
            pass
    if csv_path.exists():
        fields, rows = load_csv_rows(csv_path)
        if fields:
            return normalize_review_fieldnames(fields, rows) + ("csv",)
    return [], [], ""


def load_existing_review_rows(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    fieldnames, rows, _ = load_review_rows(path.with_suffix(".csv"), path)
    if not fieldnames:
        return {}
    return {review_record_key(row): row for row in rows}


def load_archived_backlog_keys(archive_root: Path) -> set[tuple[str, str, str]]:
    archived_keys: set[tuple[str, str, str]] = set()
    if not archive_root.exists():
        return archived_keys
    for csv_path in archive_root.rglob("optimized_batch_*.csv"):
        _, rows = load_csv_rows(csv_path)
        for row in rows:
            digest_date = str(row.get("digest_date", "")).strip()
            if digest_date:
                key_kind, key_value = review_record_key(row)
                archived_keys.add((digest_date, key_kind, key_value))
    return archived_keys


def overlay_editable_columns(row: dict[str, str], existing: dict[str, str]) -> dict[str, str]:
    updated = dict(row)
    for column in EDITABLE_REVIEW_COLUMNS:
        if existing.get(column):
            updated[column] = existing[column]
    return updated


def editable_review_hash(row: dict[str, str]) -> str:
    payload = {column: str(row.get(column, "")).strip() for column in EDITABLE_REVIEW_COLUMNS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def resolve_review_status(row: dict[str, str], baseline_hash: str = "") -> str:
    current_hash = editable_review_hash(row)
    final_decision = str(row.get("review_final_decision", "")).strip()
    final_category = str(row.get("review_final_category", "")).strip()
    notes = str(row.get("reviewer_notes", "")).strip()
    if final_decision or final_category or notes or current_hash != baseline_hash:
        return "reviewed_pending_optimization"
    return "pending_review"


def changed_editable_columns(row: dict[str, str], baseline_row: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for column in EDITABLE_REVIEW_COLUMNS:
        current_value = str(row.get(column, "")).strip()
        baseline_value = str(baseline_row.get(column, "")).strip()
        if current_value != baseline_value:
            changed.append(column)
    return changed


def resolve_admission_tier(
    row: dict[str, str],
    baseline_row: dict[str, str],
    review_status: str,
) -> tuple[str, str]:
    if review_status != "reviewed_pending_optimization":
        return "", ""

    changed_columns = changed_editable_columns(row, baseline_row)
    human_decision = str(row.get("review_final_decision", "")).strip().lower()
    human_category = str(row.get("review_final_category", "")).strip()
    notes = str(row.get("reviewer_notes", "")).strip()
    llm_decision = str(row.get("llm_decision", "")).strip().lower()
    current_category = str(row.get("category", "")).strip()

    interest_only = all(column in {"interest_level", "interest_tag"} for column in changed_columns)
    if interest_only:
        return ("observe", "manual edits only adjust interest fields; do not treat as direct rule evidence")

    if human_decision and human_decision == llm_decision and (not human_category or human_category == current_category):
        return ("apply", "manual override agrees with existing decision/category; low-risk optimization input")

    if human_decision and human_decision in {"keep", "reject"} and llm_decision == "review":
        return ("suggest", "manual decision resolves a review-queue item; use as candidate evidence, not direct truth")

    if human_category and human_category != current_category:
        return ("suggest", "manual category override differs from current category; require Codex validation before applying")

    if any(column in HUMAN_OVERRIDE_COLUMNS for column in changed_columns) or notes:
        return ("suggest", "manual override exists but should be validated by Codex before rule updates")

    return ("observe", "edit is weak or ambiguous; keep for observation only")


def ensure_backlog_review_fields(
    row: dict[str, str],
    archive_date: str,
    source_review_file: Path,
    baseline_row: dict[str, str] | None = None,
    baseline_hash: str = "",
) -> dict[str, str]:
    updated = dict(row)
    updated["digest_date"] = archive_date
    updated["source_review_file"] = str(source_review_file)
    baseline = baseline_row or {}
    previous_hash = str(updated.get("last_manual_edit_hash", "")).strip()
    current_hash = editable_review_hash(updated)
    updated["last_manual_edit_hash"] = current_hash
    updated["review_status"] = resolve_review_status(updated, baseline_hash)
    admission_tier, admission_reason = resolve_admission_tier(updated, baseline, updated["review_status"])
    updated["admission_tier"] = admission_tier
    updated["admission_reason"] = admission_reason
    if updated["review_status"] == "reviewed_pending_optimization" and not str(updated.get("reviewed_at", "")).strip():
        updated["reviewed_at"] = current_timestamp_utc()
    elif updated["review_status"] == "pending_review":
        updated["reviewed_at"] = ""
        updated["admission_tier"] = ""
        updated["admission_reason"] = ""
    if updated["review_status"] != "optimized":
        updated["archived_at"] = ""
    if previous_hash and previous_hash == current_hash and str(updated.get("reviewed_at", "")).strip():
        updated["reviewed_at"] = str(updated.get("reviewed_at", "")).strip()
    return updated


def write_backlog_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_backlog_views(
    backlog_root: Path,
    csv_path: Path,
    html_path: Path,
    xlsx_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]] | None = None,
) -> None:
    loaded_rows = rows
    if loaded_rows is None:
        _, loaded_rows, _ = load_review_rows(csv_path, xlsx_path)
    if loaded_rows is None:
        loaded_rows = []
    if not fieldnames:
        fieldnames = list(loaded_rows[0].keys()) if loaded_rows else []
    rules = json.loads(json.dumps(load_yaml_file(CANONICAL_PATHS["rules"]) or {}))
    template_text = CANONICAL_PATHS["email_template"].read_text(encoding="utf-8")
    runtime_style_path = str(RUNTIME_DEFAULTS.get("paths", {}).get("style_config", "") or "").strip()
    style_candidates: list[Path] = []
    if runtime_style_path:
        style_candidates.append(Path(runtime_style_path).resolve())
    style_candidates.append(CANONICAL_PATHS["email_style_local"])
    style_path = first_existing_path(*style_candidates)
    style_override_css = build_style_override_css(load_yaml_file(style_path) or {}) if style_path else ""
    option_map = review_option_map(rules, fieldnames)
    write_csv(csv_path, loaded_rows, fieldnames, option_map)
    write_xlsx(xlsx_path, loaded_rows, fieldnames, option_map)
    html_body = render_html_table(loaded_rows, fieldnames, template_text, style_override_css, rules, "")
    html_body = html_body.replace("</body>", build_review_table_script() + "\n</body>")
    html_path.write_text(html_body, encoding="utf-8")


def sync_review_backlog(args: Any, archive_date: str, target_dir: Path) -> None:
    backlog_root = Path(args.backlog_dir).resolve()
    runtime_defaults = getattr(args, "runtime_defaults", {}) or {}
    runtime_archive_dir = str(runtime_defaults.get("paths", {}).get("archive_dir", "") or "")
    archive_root = Path(str(getattr(args, "archive_dir", "") or runtime_archive_dir or DEFAULT_ARCHIVE_DIR)).resolve()
    active_csv = backlog_root / "review_backlog.csv"
    active_html = backlog_root / "review_backlog.html"
    active_xlsx = backlog_root / "review_backlog.xlsx"
    active_state = backlog_root / "review_backlog_state.json"
    backlog_archive_root = backlog_root / "archive"
    source_csv = target_dir / "daily_review.csv"
    source_xlsx = target_dir / "daily_review.xlsx"
    if not source_csv.exists() and not source_xlsx.exists():
        return

    source_fields, source_rows, _ = load_review_rows(source_csv, source_xlsx)
    _, baseline_rows, _ = load_review_rows(
        archive_root / archive_date / "daily_review.csv",
        archive_root / archive_date / "daily_review.xlsx",
    )
    _, backlog_rows, _ = load_review_rows(active_csv, active_xlsx)
    backlog_index = {backlog_record_key(row): dict(row) for row in backlog_rows}
    baseline_index = {review_record_key(row): row for row in baseline_rows}
    archived_keys = load_archived_backlog_keys(backlog_archive_root)

    backlog_prefix = [
        "digest_date",
        "review_status",
        "admission_tier",
        "admission_reason",
        "reviewed_at",
        "optimized_at",
        "archived_at",
        "last_manual_edit_hash",
        "source_review_file",
    ]
    merged_fieldnames = backlog_prefix + [field for field in source_fields if field not in backlog_prefix]

    for row in source_rows:
        key = (archive_date, *review_record_key(row))
        if key in archived_keys and key not in backlog_index:
            continue
        existing = backlog_index.get(key, {})
        merged = overlay_editable_columns(dict(row), existing)
        for metadata_column in backlog_prefix:
            if metadata_column in existing:
                merged[metadata_column] = existing[metadata_column]
        baseline_row = baseline_index.get(review_record_key(row), {})
        merged = ensure_backlog_review_fields(
            merged,
            archive_date,
            source_xlsx if source_xlsx.exists() else source_csv,
            baseline_row,
            editable_review_hash(baseline_row) if baseline_row else "",
        )
        backlog_index[key] = merged

    active_rows: list[dict[str, str]] = []
    archived_rows: list[dict[str, str]] = []
    for row in backlog_index.values():
        normalized = dict(row)
        row_key = backlog_record_key(normalized)
        if row_key in archived_keys and not str(normalized.get("optimized_at", "")).strip():
            continue
        if str(normalized.get("optimized_at", "")).strip():
            normalized["review_status"] = "optimized"
            normalized["admission_tier"] = ""
            normalized["admission_reason"] = "consumed by Codex and archived"
        else:
            normalized["review_status"] = str(normalized.get("review_status", "pending_review")).strip() or "pending_review"
        if normalized["review_status"] == "optimized":
            normalized["archived_at"] = current_timestamp_utc()
            archived_rows.append(normalized)
        else:
            active_rows.append(normalized)

    active_rows.sort(key=lambda item: (item.get("review_status", ""), item.get("digest_date", ""), *review_record_key(item)))
    export_backlog_views(backlog_root, active_csv, active_html, active_xlsx, merged_fieldnames, active_rows)

    state_payload = {
        "updated_at_utc": current_timestamp_utc(),
        "active_backlog_csv": str(active_csv),
        "active_backlog_file": str(active_xlsx),
        "active_counts": {
            "pending_review": sum(1 for row in active_rows if row.get("review_status") == "pending_review"),
            "reviewed_pending_optimization": sum(1 for row in active_rows if row.get("review_status") == "reviewed_pending_optimization"),
            "optimized": 0,
        },
        "admission_counts": {
            "observe": sum(1 for row in active_rows if row.get("admission_tier") == "observe"),
            "suggest": sum(1 for row in active_rows if row.get("admission_tier") == "suggest"),
            "apply": sum(1 for row in active_rows if row.get("admission_tier") == "apply"),
        },
        "archived_today": len(archived_rows),
    }
    active_state.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if archived_rows:
        batch_dir = backlog_archive_root / archive_date
        batch_dir.mkdir(parents=True, exist_ok=True)
        batch_name = datetime.now(ZoneInfo(args.timezone)).strftime("%H%M%S")
        batch_csv = batch_dir / f"optimized_batch_{batch_name}.csv"
        batch_json = batch_dir / f"optimized_batch_{batch_name}.json"
        write_backlog_csv(batch_csv, merged_fieldnames, archived_rows)
        batch_json.write_text(
            json.dumps(
                {
                    "created_at_utc": current_timestamp_utc(),
                    "row_count": len(archived_rows),
                    "source_backlog": str(active_csv),
                    "batch_csv": str(batch_csv),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def sync_review_workspace(args: Any, archive_date: str) -> None:
    work_dir = Path(args.work_dir).resolve()
    review_root = Path(args.review_workspace_dir).resolve()
    target_dir = review_root / archive_date
    target_dir.mkdir(parents=True, exist_ok=True)

    csv_source = work_dir / "daily_review.csv"
    xlsx_source = work_dir / "daily_review.xlsx"
    html_target = target_dir / "daily_review.html"
    csv_target = target_dir / "daily_review.csv"
    xlsx_target = target_dir / "daily_review.xlsx"
    source_fields, source_rows, _ = load_review_rows(csv_source, xlsx_source)
    existing_fields, existing_rows, _ = load_review_rows(csv_target, xlsx_target)
    existing_index = {review_record_key(row): row for row in existing_rows}
    merged_rows = [overlay_editable_columns(dict(row), existing_index.get(review_record_key(row), {})) for row in source_rows]
    export_backlog_views(target_dir, csv_target, html_target, xlsx_target, source_fields or existing_fields, merged_rows)

    manifest = {
        "generated_at_utc": current_timestamp_utc(),
        "source_run_dir": str(work_dir),
        "review_file": str(xlsx_target),
        "review_csv": str(csv_target),
        "review_xlsx": str(xlsx_target),
        "canonical_review_surface": str(Path(args.backlog_dir).resolve() / "review_backlog.xlsx"),
        "derived_review_views": {
            "csv": str(Path(args.backlog_dir).resolve() / "review_backlog.csv"),
            "html": str(Path(args.backlog_dir).resolve() / "review_backlog.html"),
        },
        "editable_columns": EDITABLE_REVIEW_COLUMNS,
        "archive_date": archive_date,
    }
    (target_dir / "review_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sync_review_backlog(args, archive_date, target_dir)


def archive_outputs(args: Any) -> str:
    import shutil

    work_dir = Path(args.work_dir).resolve()
    archive_root = Path(args.archive_dir).resolve()
    archive_date = resolve_archive_date(args)
    target_dir = archive_root / archive_date
    target_dir.mkdir(parents=True, exist_ok=True)

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
        source = work_dir / filename
        if source.exists():
            shutil.copy2(source, target_dir / filename)

    sync_review_workspace(args, archive_date)

    tz = ZoneInfo(args.timezone)
    cutoff_date = datetime.now(tz).date() - timedelta(days=args.retention_days)
    for child in archive_root.iterdir():
        if not child.is_dir():
            continue
        try:
            child_date = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if child_date <= cutoff_date:
            shutil.rmtree(child)
    return archive_date
