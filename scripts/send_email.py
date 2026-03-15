#!/usr/bin/env python3
from __future__ import annotations

import argparse
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

try:
    from common import load_yaml_file
except ModuleNotFoundError:
    from scripts.common import load_yaml_file


def add_attachment(message: EmailMessage, path: str) -> None:
    guessed_type, _ = mimetypes.guess_type(path)
    maintype, subtype = (guessed_type or "application/octet-stream").split("/", 1)
    data = Path(path).read_bytes()
    message.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(path).name)


def build_message(
    *,
    subject: str,
    from_name: str,
    from_email: str,
    recipient: str,
    html_body: str,
    text_body: str,
    csv_attachment: str,
    xlsx_attachment: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    add_attachment(message, csv_attachment)
    add_attachment(message, xlsx_attachment)
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description="Send exported digest via SMTP.")
    parser.add_argument("--config", required=True, help="Path to email config YAML")
    parser.add_argument("--profile", required=True, help="SMTP profile name")
    parser.add_argument("--html-body", required=True, help="HTML file to send")
    parser.add_argument("--csv-attachment", required=True, help="CSV file attachment")
    parser.add_argument("--xlsx-attachment", required=True, help="XLSX file attachment")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--text-body", default="See attached daily literature digest.", help="Plain-text fallback")
    args = parser.parse_args()

    config = load_yaml_file(args.config) or {}
    profiles = config.get("smtp_profiles", {})
    profile = profiles.get(args.profile)
    if not profile:
        raise SystemExit(f"Unknown SMTP profile: {args.profile}")

    password_env = profile.get("password_env")
    password = os.environ.get(password_env or "")
    if not password:
        raise SystemExit(f"Missing SMTP secret in environment variable: {password_env}")

    recipients = [email for email in profile.get("to_emails", []) if email]
    if not recipients:
        raise SystemExit(f"No recipients configured for profile: {args.profile}")
    html_body = Path(args.html_body).read_text(encoding="utf-8")

    smtp_host = profile["smtp_host"]
    smtp_port = int(profile["smtp_port"])
    security = profile.get("security", "ssl")
    sent_recipients: list[str] = []

    def send_all(server: smtplib.SMTP) -> None:
        server.login(profile["username"], password)
        for recipient in recipients:
            message = build_message(
                subject=args.subject,
                from_name=profile.get("from_name", ""),
                from_email=profile["from_email"],
                recipient=recipient,
                html_body=html_body,
                text_body=args.text_body,
                csv_attachment=args.csv_attachment,
                xlsx_attachment=args.xlsx_attachment,
            )
            refused = server.send_message(message)
            if refused:
                raise SystemExit(f"SMTP refused recipients: {refused}")
            sent_recipients.append(recipient)

    if security == "ssl":
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            send_all(server)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            send_all(server)

    print(f"Sent digest email via profile {args.profile} to {', '.join(sent_recipients)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
