#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from common import canonicalize_doi, canonicalize_url, normalize_title, read_jsonl, write_jsonl


def record_key(record: dict[str, Any]) -> tuple[str, str]:
    doi = canonicalize_doi(record.get("doi"))
    if doi:
        return ("doi", doi)
    url = canonicalize_url(record.get("article_url") or record.get("canonical_url"))
    if url:
        return ("url", url)
    return ("title", f"{(record.get('journal') or '').lower()}::{normalize_title(record.get('title_en'))}")


def load_decisions(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    decisions: dict[tuple[str, str], dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            final_decision = (row.get("review_final_decision") or "").strip().lower()
            final_category = (row.get("review_final_category") or "").strip()
            reviewer_notes = (row.get("reviewer_notes") or "").strip()
            if not final_decision and not final_category and not reviewer_notes:
                continue
            key_record = {
                "doi": row.get("doi"),
                "article_url": row.get("article_url"),
                "journal": row.get("journal"),
                "title_en": row.get("title_en"),
            }
            decisions[record_key(key_record)] = {
                "review_final_decision": final_decision,
                "review_final_category": final_category,
                "reviewer_notes": reviewer_notes,
            }
    return decisions


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply manual review decisions from review_queue.csv back onto reviewed records.")
    parser.add_argument("--input", required=True, help="Reviewed audit JSONL")
    parser.add_argument("--decisions-csv", required=True, help="Edited review_queue.csv with manual decision columns filled")
    parser.add_argument("--output", required=True, help="Merged reviewed JSONL")
    parser.add_argument("--keep-output", required=True, help="Final keep JSONL")
    parser.add_argument("--review-output", required=True, help="Remaining review-pending JSONL")
    parser.add_argument("--reject-output", required=True, help="Final reject JSONL")
    args = parser.parse_args()

    reviewed_records = read_jsonl(Path(args.input))
    decisions = load_decisions(Path(args.decisions_csv))
    merged: list[dict[str, Any]] = []
    keep_records: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []
    reject_records: list[dict[str, Any]] = []

    for record in reviewed_records:
        updated = dict(record)
        decision = decisions.get(record_key(record))
        if decision:
            final_decision = decision.get("review_final_decision") or updated.get("final_decision", "review")
            if final_decision not in {"keep", "review", "reject"}:
                final_decision = updated.get("final_decision", "review")
            updated["manual_review_applied"] = True
            updated["manual_review_decision"] = final_decision
            updated["reviewer_notes"] = decision.get("reviewer_notes", "")
            if decision.get("review_final_category"):
                updated["category_original"] = updated.get("category")
                updated["category"] = decision["review_final_category"]
            updated["final_decision"] = final_decision

        merged.append(updated)
        if updated.get("final_decision") == "keep":
            keep_records.append(updated)
        elif updated.get("final_decision") == "reject":
            reject_records.append(updated)
        else:
            review_records.append(updated)

    write_jsonl(Path(args.output), merged)
    write_jsonl(Path(args.keep_output), keep_records)
    write_jsonl(Path(args.review_output), review_records)
    write_jsonl(Path(args.reject_output), reject_records)
    print(
        f"Applied manual decisions to {len(merged)} reviewed records: "
        f"{len(keep_records)} keep, {len(review_records)} review, {len(reject_records)} reject."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
