#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts._bootstrap import SKILL_DIR, canonical_paths, expand_config_value
except ModuleNotFoundError:
    from _bootstrap import SKILL_DIR, canonical_paths, expand_config_value
try:
    from scripts.common import current_timestamp_utc, load_yaml_file
except ModuleNotFoundError:
    from common import current_timestamp_utc, load_yaml_file

from bio_literature_digest.ai.client import build_chat_client, parse_json_content, resolve_chat_config
from bio_literature_digest.optimization.daily_helpers import (
    add_unique,
    backlog_key,
    compact_review_row,
    iter_update_items,
    normalize_term,
    read_csv_sample,
    read_json,
    read_text,
    term_allowed,
)
from bio_literature_digest.review.backlog import load_review_rows


CANONICAL_PATHS = canonical_paths()


def run_backlog_refresh(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(SKILL_DIR / "scripts" / "refresh_review_backlog.py"),
        "--review-workspace-dir",
        str(args.review_workspace_dir),
        "--backlog-dir",
        str(args.backlog_dir),
        "--archive-dir",
        str(args.archive_dir),
        "--timezone",
        args.timezone,
    ]
    subprocess.run(command, check=True, cwd=SKILL_DIR)


def build_evidence(args: argparse.Namespace, pending_rows: list[dict[str, str]], backlog_source: str) -> dict[str, Any]:
    work_dir = args.work_dir
    metadata = read_json(work_dir / "run_metadata.json")
    status = str(metadata.get("status", "")).strip()
    if args.require_successful_run and status != "success":
        raise SystemExit(f"Current run is not successful; status={status or 'missing'}")
    return {
        "created_at_utc": current_timestamp_utc(),
        "run_metadata": metadata,
        "artifact_paths": {
            "run_metadata": str(work_dir / "run_metadata.json"),
            "rule_feedback_report": str(work_dir / "rule_feedback_report.md"),
            "classification_suggestions_json": str(work_dir / "classification_suggestions.json"),
            "classification_suggestions_md": str(work_dir / "classification_suggestions.md"),
            "glossary_candidates_md": str(work_dir / "glossary_candidates.md"),
            "review_queue_csv": str(work_dir / "review_queue.csv"),
            "backlog_source": backlog_source,
        },
        "rule_feedback_report": read_text(work_dir / "rule_feedback_report.md"),
        "classification_suggestions_json": read_json(work_dir / "classification_suggestions.json"),
        "classification_suggestions_md": read_text(work_dir / "classification_suggestions.md"),
        "glossary_candidates_md": read_text(work_dir / "glossary_candidates.md"),
        "review_queue_sample": read_csv_sample(work_dir / "review_queue.csv"),
        "reviewed_pending_rows": [
            compact_review_row(row, index)
            for index, row in enumerate(pending_rows[: args.max_candidate_rows], start=1)
        ],
    }


def load_optimizer_config(path: Path) -> dict[str, Any]:
    payload = load_yaml_file(path) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"AI config must be a mapping: {path}")
    ai_config = dict(resolve_chat_config(payload))
    opt_config = payload.get("daily_optimization")
    if isinstance(opt_config, dict):
        for key, value in opt_config.items():
            if key in {
                "model",
                "model_candidates",
                "models",
                "max_retries",
                "retry_backoff_seconds",
                "retry_max_sleep_seconds",
                "timeout_seconds",
                "max_output_tokens",
                "temperature",
                "api_key",
                "api_key_envs",
                "base_url",
            }:
                ai_config[key] = value
    ai_config.setdefault("model", "deepseek-ai/deepseek-v4-pro")
    ai_config.setdefault(
        "model_candidates",
        ["deepseek-ai/deepseek-v4-pro", "minimaxai/minimax-m2.7", "z-ai/glm-5.1", "minimaxai/minimax-m3"],
    )
    ai_config.setdefault("max_retries", 10)
    ai_config.setdefault("retry_backoff_seconds", 1.0)
    ai_config.setdefault("retry_max_sleep_seconds", 20.0)
    return ai_config


def optimizer_prompt(evidence: dict[str, Any], args: argparse.Namespace) -> list[dict[str, str]]:
    schema = {
        "selected_rows": [
            {
                "row_index": 1,
                "digest_date": "YYYY-MM-DD",
                "key_kind": "doi|url|title",
                "key_value": "canonical key",
                "stable_conclusion": "why this row is safe to consume",
            }
        ],
        "rule_updates": {
            "keep_keywords": [{"keyword": "specific phrase", "row_index": 1, "reason": "evidence"}],
            "hard_reject_keywords": [{"keyword": "specific phrase", "row_index": 1, "reason": "evidence"}],
            "category_keywords": [{"category_id": "plant-biology", "keyword": "specific phrase", "row_index": 1, "reason": "evidence"}],
        },
        "glossary_updates": [{"source": "English term", "target": "中文译法", "row_index": 1, "reason": "evidence"}],
        "deferred_rows": [{"row_index": 2, "reason": "ambiguous or weak evidence"}],
    }
    rules = (
        "只返回 JSON。只学习 review_status=reviewed_pending_optimization 的行。"
        "admission_tier=apply 可作为低风险证据；suggest 必须结合标题、摘要、近期报告验证；"
        "observe 不能写入硬规则，也不要放入 selected_rows。"
        f"最多选择 {args.max_selected_rows} 行，不能批量消费所有行。"
        "关键词必须是具体短语，不能是 study/model/method/cell/protein/gene 等泛词。"
        "glossary target 必须是中文译名。没有稳定结论时返回空 selected_rows。"
    )
    return [
        {"role": "system", "content": "你是保守的生物文献规则优化审查员。"},
        {
            "role": "user",
            "content": rules + "\nJSON schema:\n" + json.dumps(schema, ensure_ascii=False) + "\nEvidence:\n" + json.dumps(evidence, ensure_ascii=False),
        },
    ]


def call_optimizer(evidence: dict[str, Any], ai_config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    client = build_chat_client(ai_config)
    candidates = ai_config.get("model_candidates") or ai_config.get("models") or [ai_config.get("model")]
    last_error: Exception | None = None
    for model in [str(item) for item in candidates if str(item).strip()]:
        client.model = model
        try:
            text = client.chat_text(
                optimizer_prompt(evidence, args),
                temperature=float(ai_config.get("temperature", 0.0)),
                max_tokens=int(ai_config.get("max_output_tokens", 4096)),
            )
            parsed = parse_json_content(text)
            if isinstance(parsed, dict):
                parsed["_model"] = model
                return parsed
            raise ValueError("Optimizer response must be a JSON object")
        except Exception as error:  # noqa: BLE001
            last_error = error
            print(f"[optimize] model failed; model={model} error={error.__class__.__name__}: {error}", file=sys.stderr)
    raise RuntimeError("All daily optimization models failed") from last_error


def apply_ai_plan(plan: dict[str, Any], rows: list[dict[str, str]], args: argparse.Namespace) -> dict[str, Any]:
    row_by_index = {str(index): row for index, row in enumerate(rows[: args.max_candidate_rows], start=1)}
    row_by_key = {(key["digest_date"], key["key_kind"], key["key_value"]): row for row in rows for key in [backlog_key(row)]}
    rules = load_yaml_file(args.rules) or {}
    glossary = load_yaml_file(args.glossary) or {}
    applied_rules: list[dict[str, str]] = []
    applied_glossary: list[dict[str, str]] = []
    consumed_keys: dict[tuple[str, str, str], dict[str, Any]] = {}

    def resolve_row(item: dict[str, Any]) -> dict[str, str] | None:
        row = row_by_index.get(str(item.get("row_index", "")).strip())
        if row:
            return row
        key = (str(item.get("digest_date", "")).strip(), str(item.get("key_kind", "")).strip(), str(item.get("key_value", "")).strip())
        return row_by_key.get(key)

    def can_consume(row: dict[str, str]) -> bool:
        key_info = backlog_key(row)
        key = (key_info["digest_date"], key_info["key_kind"], key_info["key_value"])
        return key in consumed_keys or len(consumed_keys) < args.max_selected_rows

    def register_consumed(row: dict[str, str], item: dict[str, Any]) -> None:
        key_info = backlog_key(row)
        key = (key_info["digest_date"], key_info["key_kind"], key_info["key_value"])
        consumed_keys[key] = item

    rule_updates = plan.get("rule_updates", {})
    relevance = rules.setdefault("relevance_filter", {})
    for list_name in ["keep_keywords", "hard_reject_keywords"]:
        target_list = relevance.setdefault(list_name, [])
        for item in iter_update_items(rule_updates, list_name):
            row = resolve_row(item)
            keyword = normalize_term(str(item.get("keyword", "")))
            if not row or row.get("admission_tier") == "observe" or not term_allowed(keyword, row):
                continue
            if not can_consume(row):
                continue
            if add_unique(target_list, keyword, lambda value: str(value).strip().lower()):
                applied_rules.append({"path": f"relevance_filter.{list_name}", "keyword": keyword})
                register_consumed(row, item)

    categories = rules.setdefault("categories", [])
    category_map = {str(cat.get("id", "")): cat for cat in categories if isinstance(cat, dict)}
    for item in iter_update_items(rule_updates, "category_keywords"):
        row = resolve_row(item)
        keyword = normalize_term(str(item.get("keyword", "")))
        category_id = str(item.get("category_id", "") or row.get("review_final_category", "") if row else "").strip()
        if not row or row.get("admission_tier") == "observe" or not category_id or not term_allowed(keyword, row):
            continue
        category = category_map.get(category_id)
        if not category:
            continue
        if not can_consume(row):
            continue
        target_list = category.setdefault("keywords", [])
        if add_unique(target_list, keyword, lambda value: str(value).strip().lower()):
            applied_rules.append({"path": f"categories.{category_id}.keywords", "keyword": keyword})
            register_consumed(row, item)

    glossary_items = glossary.setdefault("replacements", [])
    for item in plan.get("glossary_updates", []) if isinstance(plan.get("glossary_updates", []), list) else []:
        if not isinstance(item, dict):
            continue
        row = resolve_row(item)
        source = normalize_term(str(item.get("source", "")))
        target = normalize_term(str(item.get("target", "")))
        if not row or row.get("admission_tier") == "observe" or not term_allowed(source, row):
            continue
        if not target or not any(ord(char) > 127 for char in target):
            continue
        if not can_consume(row):
            continue
        entry = {"source": source, "target": target}
        if add_unique(glossary_items, entry, lambda value: str(value.get("source", "")).strip().lower() if isinstance(value, dict) else ""):
            applied_glossary.append(entry)
            register_consumed(row, item)

    if applied_rules and args.apply:
        args.rules.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if applied_glossary and args.apply:
        args.glossary.write_text(yaml.safe_dump(glossary, allow_unicode=True, sort_keys=False), encoding="utf-8")

    selected_rows = []
    for digest_date, key_kind, key_value in list(consumed_keys.keys())[: args.max_selected_rows]:
        row = row_by_key[(digest_date, key_kind, key_value)]
        selected_rows.append(
            {
                "digest_date": digest_date,
                "key_kind": key_kind,
                "key_value": key_value,
                "admission_tier": row.get("admission_tier", ""),
                "stable_conclusion": str(consumed_keys[(digest_date, key_kind, key_value)].get("reason", "validated conservative update")),
            }
        )
    return {"selected_rows": selected_rows, "applied_rules": applied_rules, "applied_glossary": applied_glossary}


def write_selection(path: Path, plan: dict[str, Any], applied: dict[str, Any], evidence: dict[str, Any]) -> None:
    payload = {
        "created_at_utc": current_timestamp_utc(),
        "optimizer_model": str(plan.get("_model", "")),
        "source_run": evidence.get("artifact_paths", {}),
        "selected_rows": applied["selected_rows"],
        "applied_changes": {
            "rules": applied["applied_rules"],
            "glossary": applied["applied_glossary"],
        },
        "deferred_rows": plan.get("deferred_rows", []),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_and_finalize(args: argparse.Namespace, selection_path: Path) -> None:
    if not json.loads(selection_path.read_text(encoding="utf-8")).get("selected_rows"):
        print("[optimize] no selected rows; skip mark/finalize")
        return
    subprocess.run(
        [sys.executable, str(SKILL_DIR / "scripts" / "mark_review_backlog_optimized.py"), "--backlog-dir", str(args.backlog_dir), "--selection-json", str(selection_path)],
        check=True,
        cwd=SKILL_DIR,
    )
    subprocess.run(
        [sys.executable, str(SKILL_DIR / "scripts" / "finalize_review_backlog.py"), "--backlog-dir", str(args.backlog_dir), "--timezone", args.timezone],
        check=True,
        cwd=SKILL_DIR,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Use AI to conservatively optimize daily digest review feedback.")
    parser.add_argument("--work-dir", type=Path, default=SKILL_DIR / "var" / "work" / "current")
    parser.add_argument("--backlog-dir", type=Path, default=SKILL_DIR / "var" / "reviews" / "backlog")
    parser.add_argument("--review-workspace-dir", type=Path, default=SKILL_DIR / "var" / "reviews" / "daily-reviews")
    parser.add_argument("--archive-dir", type=Path, default=SKILL_DIR / "var" / "archives" / "daily-digests")
    parser.add_argument("--config", type=Path, default=CANONICAL_PATHS["nvidia_ai_config_local"])
    parser.add_argument("--rules", type=Path, default=CANONICAL_PATHS["rules"])
    parser.add_argument("--glossary", type=Path, default=CANONICAL_PATHS["glossary"])
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--max-candidate-rows", type=int, default=30)
    parser.add_argument("--max-selected-rows", type=int, default=8)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--mark-finalize", action="store_true")
    parser.add_argument("--allow-failed-run", action="store_false", dest="require_successful_run")
    parser.set_defaults(require_successful_run=True)
    args = parser.parse_args()
    if args.mark_finalize and not args.apply:
        raise SystemExit("--mark-finalize requires --apply so backlog state matches written config changes")

    args.work_dir = Path(expand_config_value(str(args.work_dir))).resolve()
    args.backlog_dir = Path(expand_config_value(str(args.backlog_dir))).resolve()
    args.review_workspace_dir = Path(expand_config_value(str(args.review_workspace_dir))).resolve()
    args.archive_dir = Path(expand_config_value(str(args.archive_dir))).resolve()
    args.config = Path(expand_config_value(str(args.config))).resolve()
    args.rules = Path(expand_config_value(str(args.rules))).resolve()
    args.glossary = Path(expand_config_value(str(args.glossary))).resolve()

    run_backlog_refresh(args)
    fields, rows, source = load_review_rows(args.backlog_dir / "review_backlog.csv", args.backlog_dir / "review_backlog.xlsx")
    if not fields:
        raise SystemExit(f"Backlog is empty: {args.backlog_dir}")
    pending_rows = [row for row in rows if str(row.get("review_status", "")).strip() == "reviewed_pending_optimization"]
    evidence = build_evidence(args, pending_rows, source)
    selection_path = args.backlog_dir / "optimization_selection.json"
    if not pending_rows:
        write_selection(selection_path, {"_model": "", "deferred_rows": []}, {"selected_rows": [], "applied_rules": [], "applied_glossary": []}, evidence)
        print("[optimize] no reviewed_pending_optimization rows")
        return 0

    ai_config = load_optimizer_config(args.config)
    plan = call_optimizer(evidence, ai_config, args)
    applied = apply_ai_plan(plan, pending_rows, args)
    write_selection(selection_path, plan, applied, evidence)
    if args.mark_finalize:
        mark_and_finalize(args, selection_path)
    print(json.dumps({"selection_json": str(selection_path), **applied}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
