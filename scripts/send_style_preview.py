#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PYTHON = sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a digest with a chosen style config and send it as a preview email.")
    parser.add_argument("--localized-input", required=True, help="Localized JSONL file to render")
    parser.add_argument("--rules", default=str(SKILL_DIR / "references" / "category_rules.yaml"))
    parser.add_argument("--template", default=str(SKILL_DIR / "assets" / "email_template.html"))
    parser.add_argument("--style-config", default=str(SKILL_DIR / "references" / "email_style.local.yaml"))
    parser.add_argument("--email-config", default=str(SKILL_DIR / "references" / "email_config.local.yaml"))
    parser.add_argument("--smtp-profile", default="qq_mail")
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

    subprocess.run(
        [
            PYTHON,
            str(SCRIPT_DIR / "export_digest.py"),
            "--input",
            args.localized_input,
            "--rules",
            args.rules,
            "--html-output",
            str(html_path),
            "--csv-output",
            str(csv_path),
            "--xlsx-output",
            str(xlsx_path),
            "--template",
            args.template,
            "--style-config",
            args.style_config,
        ],
        check=True,
    )

    subprocess.run(
        [
            PYTHON,
            str(SCRIPT_DIR / "send_email.py"),
            "--config",
            args.email_config,
            "--profile",
            args.smtp_profile,
            "--html-body",
            str(html_path),
            "--csv-attachment",
            str(csv_path),
            "--xlsx-attachment",
            str(xlsx_path),
            "--subject",
            args.subject,
        ],
        check=True,
    )
    print(f"Preview email sent. Artifacts: {work_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
