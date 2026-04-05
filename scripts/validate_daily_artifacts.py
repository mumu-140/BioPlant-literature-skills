#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


CORE_ARTIFACTS = {
    "digest.html": "Rendered email body",
    "digest.csv": "Tabular digest attachment",
    "digest.xlsx": "Spreadsheet digest attachment",
    "review_queue.html": "Rendered review queue",
    "review_queue.csv": "Tabular review queue",
    "review_queue.xlsx": "Spreadsheet review queue",
    "run_metadata.json": "Machine-readable run status and counts",
}

OPTIONAL_ARTIFACTS = {
    "raw_records.jsonl": "Fetched raw records",
    "normalized_records.jsonl": "Normalized records",
    "final_review_queue.jsonl": "Review records after manual merge",
    "daily_review.html": "Rendered daily review sheet",
    "daily_review.csv": "Editable daily review sheet",
    "daily_review.xlsx": "Spreadsheet daily review sheet",
    "rule_feedback_report.md": "Rule feedback notes",
    "classification_suggestions.md": "Suggested category fixes",
    "classification_suggestions.json": "Suggested category fixes in JSON",
    "glossary_candidates.md": "Glossary candidate report",
}


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def load_metadata(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_run_dir(run_dir: Path, *, allow_empty_digest: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    artifact_summary: dict[str, dict[str, Any]] = {}

    for filename, description in CORE_ARTIFACTS.items():
        path = run_dir / filename
        exists = path.exists()
        size_bytes = path.stat().st_size if exists else 0
        artifact_summary[filename] = {
            "description": description,
            "path": str(path),
            "exists": exists,
            "size_bytes": size_bytes,
        }
        if not exists:
            issues.append(f"Missing core artifact: {filename}")
            continue
        if size_bytes == 0:
            issues.append(f"Empty core artifact: {filename}")

    metadata: dict[str, Any] | None = None
    metadata_path = run_dir / "run_metadata.json"
    if metadata_path.exists() and metadata_path.stat().st_size > 0:
        metadata = load_metadata(metadata_path)
        status = str(metadata.get("status", "") or "")
        if status != "success":
            failed_step = metadata.get("failed_step") or metadata.get("current_step") or "unknown"
            failure_message = metadata.get("failure_message") or "no failure message recorded"
            issues.append(f"Run metadata status is {status or 'missing'} at step {failed_step}: {failure_message}")
        else:
            notes.append("Run metadata status is success.")
        window = metadata.get("window", {})
        if not window.get("start_utc") or not window.get("end_utc"):
            warnings.append("Run metadata is missing an explicit UTC window.")

    digest_rows = count_csv_rows(run_dir / "digest.csv")
    review_rows = count_csv_rows(run_dir / "review_queue.csv")
    artifact_summary["digest.csv"]["row_count"] = digest_rows
    artifact_summary["review_queue.csv"]["row_count"] = review_rows

    if digest_rows == 0 and not allow_empty_digest:
        warnings.append("digest.csv contains 0 data rows.")
    if review_rows == 0:
        notes.append("review_queue.csv contains 0 data rows.")

    if metadata:
        counts = metadata.get("counts", {})
        metadata_digest_rows = counts.get("digest_csv_rows")
        metadata_review_rows = counts.get("review_queue_csv_rows")
        if metadata_digest_rows is not None and metadata_digest_rows != digest_rows:
            issues.append(
                f"digest.csv row count mismatch: metadata={metadata_digest_rows}, actual={digest_rows}"
            )
        if metadata_review_rows is not None and metadata_review_rows != review_rows:
            issues.append(
                f"review_queue.csv row count mismatch: metadata={metadata_review_rows}, actual={review_rows}"
            )

    for filename, description in OPTIONAL_ARTIFACTS.items():
        path = run_dir / filename
        if path.exists():
            notes.append(f"Optional artifact present: {filename}")
        else:
            notes.append(f"Optional artifact missing: {filename} ({description})")

    status = "ok"
    exit_code = 0
    if issues:
        status = "error"
        exit_code = 1
    elif warnings:
        status = "warning"
        exit_code = 2

    return {
        "status": status,
        "exit_code": exit_code,
        "run_dir": str(run_dir),
        "issues": issues,
        "warnings": warnings,
        "notes": notes,
        "artifacts": artifact_summary,
    }


def resolve_run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir:
        return Path(args.run_dir).resolve()
    if args.archive_dir and args.date:
        return (Path(args.archive_dir).resolve() / args.date).resolve()
    raise SystemExit("Provide --run-dir or both --archive-dir and --date")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the standardized output contract for a digest run.")
    parser.add_argument("--run-dir", help="Directory containing the latest run outputs")
    parser.add_argument("--archive-dir", help="Archive root containing YYYY-MM-DD subdirectories")
    parser.add_argument("--date", help="Archive date to inspect, in YYYY-MM-DD")
    parser.add_argument("--allow-empty-digest", action="store_true", help="Do not warn when digest.csv has 0 rows")
    parser.add_argument("--json-output", help="Optional path to write the validation result as JSON")
    args = parser.parse_args()

    run_dir = resolve_run_dir(args)
    result = validate_run_dir(run_dir, allow_empty_digest=args.allow_empty_digest)

    lines = [f"# Daily Artifact Validation", "", f"- Run dir: {run_dir}", f"- Status: {result['status']}"]
    if result["issues"]:
        lines.append("")
        lines.append("## Issues")
        lines.extend(f"- {issue}" for issue in result["issues"])
    if result["warnings"]:
        lines.append("")
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    if result["notes"]:
        lines.append("")
        lines.append("## Notes")
        lines.extend(f"- {note}" for note in result["notes"])
    report = "\n".join(lines) + "\n"

    if args.json_output:
        Path(args.json_output).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report, end="")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
