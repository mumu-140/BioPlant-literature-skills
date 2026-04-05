#!/usr/bin/env python3
from __future__ import annotations

import argparse
import email
import imaplib
import os
import re
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path


def decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", name).strip().strip(".")
    return cleaned or "attachment"


def unique_path(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / sanitize_filename(name)
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 10000):
        retry = dest_dir / f"{stem}_{index}{suffix}"
        if not retry.exists():
            return retry
    raise RuntimeError(f"Unable to allocate unique filename for {name}")


def part_filename(part: Message) -> str:
    raw = part.get_filename()
    if raw:
        return decode_mime(raw)
    return ""


def body_text(message: Message) -> str:
    chunks: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() != "text":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            chunks.append(payload.decode(charset, errors="ignore"))
    else:
        payload = message.get_payload(decode=True)
        if payload is not None:
            charset = message.get_content_charset() or "utf-8"
            chunks.append(payload.decode(charset, errors="ignore"))
    return "\n".join(chunks)


def message_matches(message: Message, keyword: str) -> tuple[bool, str]:
    keyword_lower = keyword.lower()
    subject = decode_mime(message.get("Subject"))
    from_value = decode_mime(message.get("From"))
    if keyword_lower in subject.lower():
        return True, f"subject:{subject}"
    if keyword_lower in from_value.lower():
        return True, f"from:{from_value}"

    for part in message.walk():
        filename = part_filename(part)
        if filename and keyword_lower in filename.lower():
            return True, f"attachment:{filename}"

    text = body_text(message)
    if keyword_lower in text.lower():
        return True, "body"
    return False, ""


def iter_attachments(message: Message) -> list[tuple[str, bytes]]:
    attachments: list[tuple[str, bytes]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part_filename(part)
        disposition = (part.get_content_disposition() or "").lower()
        if not filename and disposition != "attachment":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        attachments.append((filename or "attachment.bin", payload))
    return attachments


def fetch_message_ids(client: imaplib.IMAP4_SSL) -> list[bytes]:
    for criteria in ('TEXT "plantCARE"', 'SUBJECT "plantCARE"', "ALL"):
        status, data = client.search(None, criteria)
        if status == "OK" and data and data[0]:
            ids = data[0].split()
            if ids:
                return ids
    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download matching attachments from an IMAP inbox.")
    parser.add_argument("--imap-host", default="imap.qq.com")
    parser.add_argument("--imap-port", type=int, default=993)
    parser.add_argument("--username", default="", help="IMAP mailbox username, for example your_account@qq.com.")
    parser.add_argument("--password-env", default="QQ_MAIL_APP_PASSWORD")
    parser.add_argument("--mailbox", default="INBOX")
    parser.add_argument("--keyword", default="Bio Digest")
    parser.add_argument(
        "--output-dir",
        default="tmp/imap_attachments",
        help="Directory where attachments will be saved.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit on matched messages. 0 means no limit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.username.strip():
        raise SystemExit("--username is required")
    password = os.environ.get(args.password_env)
    if not password:
        raise SystemExit(f"Missing required environment variable: {args.password_env}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = imaplib.IMAP4_SSL(args.imap_host, args.imap_port)
    try:
        client.login(args.username, password)
        status, _ = client.select(args.mailbox)
        if status != "OK":
            raise SystemExit(f"Unable to open mailbox: {args.mailbox}")

        ids = fetch_message_ids(client)
        matched_messages = 0
        saved_files: list[Path] = []

        for message_id in reversed(ids):
            status, data = client.fetch(message_id, "(RFC822)")
            if status != "OK" or not data:
                continue
            raw_message = next((item[1] for item in data if isinstance(item, tuple) and len(item) > 1), None)
            if not raw_message:
                continue
            message = email.message_from_bytes(raw_message)
            matched, reason = message_matches(message, args.keyword)
            if not matched:
                continue

            attachments = iter_attachments(message)
            if not attachments:
                continue

            matched_messages += 1
            subject = decode_mime(message.get("Subject")) or "(no subject)"
            print(f"[match] id={message_id.decode()} reason={reason} subject={subject}")
            for filename, payload in attachments:
                target = unique_path(output_dir, filename)
                target.write_bytes(payload)
                saved_files.append(target)
                print(f"[saved] {target}")

            if args.limit and matched_messages >= args.limit:
                break

        print(f"[summary] matched_messages={matched_messages} saved_files={len(saved_files)} output_dir={output_dir}")
        return 0
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
