#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import smtplib
import subprocess
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    from scripts._bootstrap import canonical_paths, load_runtime_config
except ModuleNotFoundError:
    from _bootstrap import canonical_paths, load_runtime_config
try:
    from scripts.common import load_yaml_file
except ModuleNotFoundError:
    from common import load_yaml_file

# _bootstrap put src/ on sys.path, so this resolves without extra path juggling.
from bio_literature_digest.masking import (  # noqa: E402
    mask_email,
    mask_email_list,
    mask_email_text,
)


CANONICAL_PATHS = canonical_paths()


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


def parse_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def dedupe_emails(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_email(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def resolve_users_config_path(explicit_path: str | None = None) -> Path:
    if explicit_path:
        return Path(explicit_path).resolve()
    runtime = load_runtime_config()
    configured_path = str(runtime.get("paths", {}).get("users_config", "") or "").strip()
    if configured_path:
        return Path(configured_path).resolve()
    return CANONICAL_PATHS["users_config_local"].resolve()


def load_profile_recipients_from_users_config(users_config_path: Path, smtp_profile: str) -> list[str]:
    if not users_config_path.exists():
        return []
    payload = load_yaml_file(users_config_path) or {}
    if not isinstance(payload, dict):
        return []
    users = payload.get("users")
    if not isinstance(users, list):
        return []
    recipients: list[str] = []
    for user in users:
        if not isinstance(user, dict):
            continue
        email = normalize_email(user.get("email"))
        if not email:
            continue
        if not parse_bool(user.get("is_active"), default=True):
            continue
        if not parse_bool(user.get("receives_digest"), default=True):
            continue
        profile = str(user.get("smtp_profile", "") or "").strip()
        if profile and profile != smtp_profile:
            continue
        recipients.append(email)
    return dedupe_emails(recipients)


def resolve_recipients(profile: dict[str, object], *, smtp_profile: str, users_config_path: Path) -> list[str]:
    recipients = load_profile_recipients_from_users_config(users_config_path, smtp_profile)
    if recipients:
        return recipients
    override = profile.get("to_emails_override")
    if isinstance(override, list):
        recipients = dedupe_emails([str(email) for email in override if email])
        if recipients:
            return recipients
    fallback = profile.get("to_emails", [])
    if isinstance(fallback, list):
        return dedupe_emails([str(email) for email in fallback if email])
    return []


def personalized_login_url(url: str, recipient: str) -> str:
    parsed = urlparse(url)
    if parsed.path.endswith("/digests/today"):
        return add_or_replace_query(urlunparse(parsed._replace(path="/login", query="")), next="/digests/today", email=recipient)
    if parsed.path.endswith("/login"):
        next_path = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("next", "/digests/today")
        return add_or_replace_query(url, next=next_path, email=recipient)
    return url


def personalize_html_body(html_body: str, recipient: str) -> str:
    def replace_href(match: re.Match[str]) -> str:
        return f'href="{personalized_login_url(match.group(1), recipient)}"'

    return re.sub(r'href="(https://[^"]+/(?:login\?[^"]*|digests/today[^"]*))"', replace_href, html_body)


def personalize_text_body(text_body: str, recipient: str, html_body: str) -> str:
    match = re.search(r'href="(https://[^"]+/login\?[^"]*)"', html_body)
    if not match:
        return text_body
    return (
        f"{text_body}\n\nWeb login for {recipient}: "
        f"{personalized_login_url(match.group(1), recipient)}"
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


def parse_agently_json(stdout: str) -> dict[str, object]:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"agently-cli did not return JSON: {stdout.strip()}")
    payload = json.loads(stdout[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError("agently-cli returned a non-object JSON payload")
    return payload


def safe_body_filename(recipient: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", recipient.lower()).strip("-")
    return f".agently-body-{slug or 'recipient'}.html"


def relative_path_for_cli(path: str | Path, cwd: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(cwd.resolve()))
    except ValueError as exc:
        raise RuntimeError(f"agently-cli path must be inside {cwd}: {resolved}") from exc


def run_agently_send_command(args: list[str], cwd: Path) -> dict[str, object]:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        raise RuntimeError(f"agently-cli send failed with exit {completed.returncode}: {detail}")
    return parse_agently_json(completed.stdout)


def send_agently_message(
    *,
    recipient: str,
    subject: str,
    html_body: str,
    csv_attachment_path: str | Path,
    xlsx_attachment_path: str | Path,
    work_dir: Path,
    cli_bin: str,
) -> None:
    body_path = work_dir / safe_body_filename(recipient)
    body_path.write_text(html_body, encoding="utf-8")
    base_command = [
        cli_bin,
        "message",
        "+send",
        "--to",
        recipient,
        "--subject",
        subject,
        "--body-file",
        relative_path_for_cli(body_path, work_dir),
        "--attachment",
        relative_path_for_cli(csv_attachment_path, work_dir),
        "--attachment",
        relative_path_for_cli(xlsx_attachment_path, work_dir),
    ]
    try:
        first_payload = run_agently_send_command(base_command, work_dir)
        data = first_payload.get("data") if isinstance(first_payload.get("data"), dict) else {}
        token = str(data.get("confirmation_token", "") if isinstance(data, dict) else "").strip()
        if not token:
            raise RuntimeError(f"agently-cli did not return confirmation_token: {first_payload}")
        final_payload = run_agently_send_command(base_command + ["--confirmation-token", token], work_dir)
        final_data = final_payload.get("data") if isinstance(final_payload.get("data"), dict) else {}
        queued = bool(final_payload.get("queued")) or bool(final_data.get("queued") if isinstance(final_data, dict) else False)
        if not queued:
            raise RuntimeError(f"agently-cli did not queue message: {final_payload}")
    finally:
        try:
            body_path.unlink()
        except FileNotFoundError:
            pass


def send_agently_digest_email(
    *,
    config: dict[str, object],
    profile_name: str,
    html_body_path: str | Path,
    csv_attachment_path: str | Path,
    xlsx_attachment_path: str | Path,
    subject: str,
    users_config: str | Path | None,
) -> list[str]:
    profiles = config.get("agently_profiles", {})
    profile = profiles.get(profile_name) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        raise SystemExit(f"Unknown Agently profile: {profile_name}")
    users_profile = str(profile.get("users_profile", "") or profile_name).strip()
    users_config_path = resolve_users_config_path(str(users_config) if users_config else None)
    recipients = resolve_recipients(profile, smtp_profile=users_profile, users_config_path=users_config_path)
    if not recipients:
        raise SystemExit(
            f"No recipients configured for profile: {profile_name}. "
            f"Checked users config: {users_config_path} using users_profile={users_profile}."
        )

    html_body = Path(html_body_path).read_text(encoding="utf-8")
    work_dir = Path(html_body_path).resolve().parent
    cli_bin = str(profile.get("cli_bin", "agently-cli") or "agently-cli")
    sent_recipients: list[str] = []
    failed_recipients: dict[str, str] = {}

    for recipient in recipients:
        recipient_html_body = personalize_html_body(html_body, recipient)
        try:
            send_agently_message(
                recipient=recipient,
                subject=subject,
                html_body=recipient_html_body,
                csv_attachment_path=csv_attachment_path,
                xlsx_attachment_path=xlsx_attachment_path,
                work_dir=work_dir,
                cli_bin=cli_bin,
            )
        except Exception as exc:  # noqa: BLE001 - include all CLI/local failures for SMTP fallback.
            failed_recipients[recipient] = str(exc)
            print(
                f"[warn] Agently send failed for {mask_email(recipient)}: {mask_email_text(str(exc))}",
                file=sys.stderr,
            )
            continue
        sent_recipients.append(recipient)

    if failed_recipients:
        fallback_profile = str(profile.get("fallback_smtp_profile", "") or "").strip()
        if not fallback_profile:
            failed = ", ".join(
                f"{mask_email(recipient)}: {mask_email_text(reason)}"
                for recipient, reason in failed_recipients.items()
            )
            raise SystemExit(f"Agently send incomplete. Failed recipients: {failed}")
        fallback_sent = send_smtp_digest_email(
            config=config,
            profile_name=fallback_profile,
            html_body_path=html_body_path,
            csv_attachment_path=csv_attachment_path,
            xlsx_attachment_path=xlsx_attachment_path,
            subject=subject,
            users_config=users_config,
            recipients_override=list(failed_recipients),
        )
        sent_recipients.extend(fallback_sent)
    return sent_recipients


def send_smtp_digest_email(
    *,
    config: dict[str, object],
    profile_name: str,
    html_body_path: str | Path,
    csv_attachment_path: str | Path,
    xlsx_attachment_path: str | Path,
    subject: str,
    text_body: str = "See attached daily literature digest.",
    users_config: str | Path | None = None,
    recipients_override: list[str] | None = None,
    max_attempts: int = 3,
    retry_sleep_seconds: int = 20,
) -> list[str]:
    profiles = config.get("smtp_profiles", {})
    profile = profiles.get(profile_name)
    if not profile:
        raise SystemExit(f"Unknown SMTP profile: {profile_name}")

    password_env = profile.get("password_env")
    password = os.environ.get(password_env or "")
    if not password:
        raise SystemExit(f"Missing SMTP secret in environment variable: {password_env}")

    users_config_path = resolve_users_config_path(str(users_config) if users_config else None)
    recipients = dedupe_emails(recipients_override or [])
    if not recipients:
        recipients = resolve_recipients(profile, smtp_profile=profile_name, users_config_path=users_config_path)
    if not recipients:
        raise SystemExit(
            f"No recipients configured for profile: {profile_name}. "
            f"Checked users config: {users_config_path} and profile fallback fields to_emails_override/to_emails."
        )
    html_body = Path(html_body_path).read_text(encoding="utf-8")

    smtp_host = profile["smtp_host"]
    smtp_port = int(profile["smtp_port"])
    security = profile.get("security", "ssl")
    sent_recipients: list[str] = []
    failed_recipients: dict[str, str] = {}
    pending_recipients = list(recipients)
    max_attempts = max(1, int(max_attempts))
    retry_sleep_seconds = max(0, int(retry_sleep_seconds))

    def mark_failed_recipient(recipient: str, reason: str, pending: list[str]) -> None:
        failed_recipients[recipient] = reason
        if recipient in pending:
            pending.remove(recipient)
        print(
            f"[warn] SMTP permanent failure for {mask_email(recipient)}: {mask_email_text(reason)}",
            file=sys.stderr,
        )

    def send_all(server: smtplib.SMTP, pending: list[str]) -> None:
        server.login(profile["username"], password)
        for recipient in list(pending):
            recipient_html_body = personalize_html_body(html_body, recipient)
            message = build_message(
                subject=subject,
                from_name=profile.get("from_name", ""),
                from_email=profile["from_email"],
                recipient=recipient,
                html_body=recipient_html_body,
                text_body=personalize_text_body(text_body, recipient, recipient_html_body),
                csv_attachment=str(csv_attachment_path),
                xlsx_attachment=str(xlsx_attachment_path),
            )
            try:
                refused = server.send_message(message)
            except smtplib.SMTPDataError as exc:
                if 400 <= int(exc.smtp_code) < 500:
                    raise
                mark_failed_recipient(recipient, f"{exc.smtp_code} {exc.smtp_error!r}", pending)
                continue
            except smtplib.SMTPRecipientsRefused as exc:
                mark_failed_recipient(recipient, str(exc.recipients), pending)
                continue
            if refused:
                mark_failed_recipient(recipient, str(refused), pending)
                continue
            sent_recipients.append(recipient)
            pending.remove(recipient)

    def send_once(pending: list[str]) -> None:
        if security == "ssl":
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                send_all(server, pending)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                send_all(server, pending)

    transient_errors = (
        OSError,
        TimeoutError,
        smtplib.SMTPConnectError,
        smtplib.SMTPServerDisconnected,
        smtplib.SMTPHeloError,
    )
    for attempt in range(1, max_attempts + 1):
        try:
            send_once(pending_recipients)
            if not pending_recipients:
                break
        except transient_errors as exc:
            if attempt >= max_attempts:
                raise
            print(
                f"[warn] SMTP transient failure attempt {attempt}/{max_attempts}: "
                f"{mask_email_text(str(exc))}. "
                f"Retrying in {retry_sleep_seconds}s for remaining {len(pending_recipients)} recipients.",
                file=sys.stderr,
            )
            time.sleep(retry_sleep_seconds)
    if pending_recipients:
        raise SystemExit(
            f"SMTP send incomplete. Unsent recipients: {mask_email_list(pending_recipients)}"
        )
    if failed_recipients:
        failed = ", ".join(
            f"{mask_email(recipient)}: {mask_email_text(reason)}"
            for recipient, reason in failed_recipients.items()
        )
        raise SystemExit(f"SMTP send incomplete. Failed recipients: {failed}")
    return sent_recipients


def send_digest_email(
    *,
    config_path: str | Path,
    profile_name: str,
    html_body_path: str | Path,
    csv_attachment_path: str | Path,
    xlsx_attachment_path: str | Path,
    subject: str,
    text_body: str = "See attached daily literature digest.",
    users_config: str | Path | None = None,
    max_attempts: int = 3,
    retry_sleep_seconds: int = 20,
) -> list[str]:
    config = load_yaml_file(config_path) or {}
    agently_profiles = config.get("agently_profiles", {})
    if isinstance(agently_profiles, dict) and profile_name in agently_profiles:
        return send_agently_digest_email(
            config=config,
            profile_name=profile_name,
            html_body_path=html_body_path,
            csv_attachment_path=csv_attachment_path,
            xlsx_attachment_path=xlsx_attachment_path,
            subject=subject,
            users_config=users_config,
        )
    return send_smtp_digest_email(
        config=config,
        profile_name=profile_name,
        html_body_path=html_body_path,
        csv_attachment_path=csv_attachment_path,
        xlsx_attachment_path=xlsx_attachment_path,
        subject=subject,
        text_body=text_body,
        users_config=users_config,
        max_attempts=max_attempts,
        retry_sleep_seconds=retry_sleep_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Send exported digest via SMTP.")
    parser.add_argument("--config", required=True, help="Path to email config YAML")
    parser.add_argument("--profile", required=True, help="SMTP profile name")
    parser.add_argument("--html-body", required=True, help="HTML file to send")
    parser.add_argument("--csv-attachment", required=True, help="CSV file attachment")
    parser.add_argument("--xlsx-attachment", required=True, help="XLSX file attachment")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--text-body", default="See attached daily literature digest.", help="Plain-text fallback")
    parser.add_argument(
        "--users-config",
        help="Path to the users config file (single source of recipient accounts).",
    )
    parser.add_argument("--max-attempts", type=int, default=3, help="SMTP max attempts for transient network failures")
    parser.add_argument("--retry-sleep-seconds", type=int, default=20, help="Sleep seconds between SMTP retries")
    args = parser.parse_args()

    sent_recipients = send_digest_email(
        config_path=args.config,
        profile_name=args.profile,
        html_body_path=args.html_body,
        csv_attachment_path=args.csv_attachment,
        xlsx_attachment_path=args.xlsx_attachment,
        subject=args.subject,
        text_body=args.text_body,
        users_config=args.users_config,
        max_attempts=args.max_attempts,
        retry_sleep_seconds=args.retry_sleep_seconds,
    )
    print(
        f"Sent digest email via profile {args.profile} to "
        f"{len(sent_recipients)} recipient(s): {mask_email_list(sent_recipients)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
