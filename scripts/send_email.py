#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    from common import load_yaml_file
except ModuleNotFoundError:
    from scripts.common import load_yaml_file
try:
    from project_layout import load_runtime_config
except ModuleNotFoundError:
    from scripts.project_layout import load_runtime_config


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def add_attachment(message: EmailMessage, path: str) -> None:
    guessed_type, _ = mimetypes.guess_type(path)
    maintype, subtype = (guessed_type or "application/octet-stream").split("/", 1)
    data = Path(path).read_bytes()
    message.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(path).name)


def add_or_replace_query(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query_items = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in params]
    query_items.extend((key, value) for key, value in params.items())
    return urlunparse(parsed._replace(query=urlencode(query_items, doseq=True)))


def load_simple_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_web_backend_env_path(explicit_path: str | None = None) -> Path | None:
    if explicit_path:
        return Path(explicit_path).resolve()
    from_env = str(os.environ.get("BIO_DIGEST_WEB_BACKEND_ENV_FILE", "") or "").strip()
    if from_env:
        return Path(from_env).resolve()
    runtime = load_runtime_config()
    web_root = str(runtime.get("web", {}).get("project_root", "") or "").strip()
    if not web_root:
        return None
    tools_dir = Path(web_root).resolve() / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    try:
        from instance_paths import get_instance_paths  # type: ignore
    except ModuleNotFoundError:
        return None
    return get_instance_paths(Path(web_root).resolve()).backend_env_file


def build_email_login_token(email: str, web_backend_env_path: Path | None) -> str:
    env_values = load_simple_env(web_backend_env_path) if web_backend_env_path else {}
    session_secret = env_values.get("SESSION_SECRET", "change-me")
    ttl_hours = int(env_values.get("EMAIL_LOGIN_TTL_HOURS", "168"))
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
    payload = {
        "sub": email.strip().lower(),
        "kind": "email-login",
        "exp": int(expires_at.timestamp()),
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    signature = hmac.new(session_secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def personalized_login_url(url: str, recipient: str, web_backend_env_path: Path | None) -> str:
    token = build_email_login_token(recipient, web_backend_env_path)
    parsed = urlparse(url)
    if parsed.path.endswith("/digests/today"):
        return add_or_replace_query(urlunparse(parsed._replace(path="/login", query="")), next="/digests/today", email=recipient, token=token)
    if parsed.path.endswith("/login"):
        next_path = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("next", "/digests/today")
        return add_or_replace_query(url, next=next_path, email=recipient, token=token)
    return url


def personalize_html_body(html_body: str, recipient: str, web_backend_env_path: Path | None) -> str:
    def replace_href(match: re.Match[str]) -> str:
        return f'href="{personalized_login_url(match.group(1), recipient, web_backend_env_path)}"'

    return re.sub(r'href="(https://[^"]+/(?:login\?[^"]*|digests/today[^"]*))"', replace_href, html_body)


def personalize_text_body(text_body: str, recipient: str, html_body: str, web_backend_env_path: Path | None) -> str:
    match = re.search(r'href="(https://[^"]+/login\?[^"]*)"', html_body)
    if not match:
        return text_body
    return (
        f"{text_body}\n\nWeb login for {recipient}: "
        f"{personalized_login_url(match.group(1), recipient, web_backend_env_path)}"
    )


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
    parser.add_argument("--web-backend-env-file", help="Optional backend .env file used to personalize email login links")
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
    web_backend_env_path = resolve_web_backend_env_path(args.web_backend_env_file)

    smtp_host = profile["smtp_host"]
    smtp_port = int(profile["smtp_port"])
    security = profile.get("security", "ssl")
    sent_recipients: list[str] = []

    def send_all(server: smtplib.SMTP) -> None:
        server.login(profile["username"], password)
        for recipient in recipients:
            recipient_html_body = personalize_html_body(html_body, recipient, web_backend_env_path)
            message = build_message(
                subject=args.subject,
                from_name=profile.get("from_name", ""),
                from_email=profile["from_email"],
                recipient=recipient,
                html_body=recipient_html_body,
                text_body=personalize_text_body(args.text_body, recipient, recipient_html_body, web_backend_env_path),
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
