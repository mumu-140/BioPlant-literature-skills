#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

try:
    from scripts.common import load_yaml_file, read_jsonl
except ModuleNotFoundError:
    from common import load_yaml_file, read_jsonl
try:
    from scripts.export_digest import build_style_override_css, prepare_export_records, render_html_table, review_option_map, write_csv, write_xlsx
except ModuleNotFoundError:
    from export_digest import build_style_override_css, prepare_export_records, render_html_table, review_option_map, write_csv, write_xlsx
try:
    from scripts.send_email import send_digest_email
except ModuleNotFoundError:
    from send_email import send_digest_email
try:
    from scripts._bootstrap import canonical_paths, load_runtime_config
except ModuleNotFoundError:
    from _bootstrap import canonical_paths, load_runtime_config
CANONICAL_PATHS = canonical_paths()
RUNTIME_DEFAULTS = load_runtime_config()


def runtime_path(key: str, fallback_key: str) -> str:
    configured = str(RUNTIME_DEFAULTS.get("paths", {}).get(key, "") or "").strip()
    if configured:
        return configured
    return str(CANONICAL_PATHS[fallback_key])


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a digest with a chosen style config and send it as a preview email.")
    parser.add_argument("--localized-input", required=True, help="Localized JSONL file to render")
    parser.add_argument("--rules", default=runtime_path("rules", "rules"))
    parser.add_argument("--template", default=runtime_path("template", "email_template"))
    parser.add_argument("--style-config", default=runtime_path("style_config", "email_style_local"))
    parser.add_argument("--email-config", default=runtime_path("email_config", "email_config_local"))
    parser.add_argument("--users-config", default=runtime_path("users_config", "users_config_local"))
    parser.add_argument(
        "--smtp-profile",
        default=str(RUNTIME_DEFAULTS.get("delivery", {}).get("smtp_profile", "") or "primary_smtp"),
    )
    parser.add_argument(
        "--display-timezone",
        default=str(RUNTIME_DEFAULTS.get("delivery", {}).get("timezone", "") or "Asia/Shanghai"),
    )
    parser.add_argument("--subject", default="Bio Digest Style Preview")
    parser.add_argument("--work-dir", help="Optional output directory")
    args = parser.parse_args()

    if args.work_dir:
        work_dir = Path(args.work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="bio-style-preview-"))

    html_path = work_dir / "digest.html"
    csv_path = work_dir / "digest.csv"
    xlsx_path = work_dir / "digest.xlsx"

    records = read_jsonl(Path(args.localized_input))
    rules = load_yaml_file(args.rules) or {}
    template_text = Path(args.template).read_text(encoding="utf-8")
    style_override_css = build_style_override_css(load_yaml_file(args.style_config) or {})
    records, _context = prepare_export_records(records, rules, args.display_timezone)
    columns = list((rules.get("output_schema", {}) or {}).get("required_columns", []))
    if not columns and records:
        columns = list(records[0].keys())
    option_map = review_option_map(rules, columns)
    html_path.write_text(
        render_html_table(records, columns, template_text, style_override_css, rules, ""),
        encoding="utf-8",
    )
    write_csv(csv_path, records, columns, option_map)
    write_xlsx(xlsx_path, records, columns, option_map)

    send_digest_email(
        config_path=args.email_config,
        profile_name=args.smtp_profile,
        html_body_path=html_path,
        csv_attachment_path=csv_path,
        xlsx_attachment_path=xlsx_path,
        subject=args.subject,
        users_config=args.users_config,
    )
    print(f"Preview email sent. Artifacts: {work_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
