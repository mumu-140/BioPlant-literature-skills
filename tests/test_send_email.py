#!/usr/bin/env python3
"""Unified tests for scripts/send_email.py.

Merged from:
  - test_send_email.py (build_message)
  - test_send_email_recipients.py (resolve_recipients)
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.send_email import build_message, resolve_recipients


class SendEmailBuildMessageTest(unittest.TestCase):
    def test_build_message_targets_single_recipient_and_adds_attachments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-email-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            csv_path = tmpdir_path / "digest.csv"
            xlsx_path = tmpdir_path / "digest.xlsx"
            csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
            xlsx_path.write_bytes(b"fake-xlsx")

            message = build_message(
                subject="Test",
                from_name="Bio Literature Digest",
                from_email="sender@example.com",
                recipient="receiver@example.com",
                html_body="<html><body>Hi</body></html>",
                text_body="Hi",
                csv_attachment=str(csv_path),
                xlsx_attachment=str(xlsx_path),
            )

            self.assertEqual(message["To"], "receiver@example.com")
            self.assertEqual(message["Subject"], "Test")
            attachments = list(message.iter_attachments())
            self.assertEqual(len(attachments), 2)
            filenames = {attachment.get_filename() for attachment in attachments}
            self.assertEqual(filenames, {"digest.csv", "digest.xlsx"})


class SendEmailRecipientsTest(unittest.TestCase):
    def test_resolve_recipients_prefers_users_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-users-config-") as tmpdir:
            users_config = Path(tmpdir) / "users.yaml"
            users_config.write_text(
                "\n".join(
                    [
                        "users:",
                        "  - uid: UDI-1",
                        "    email: active@example.com",
                        "    is_active: true",
                        "    receives_digest: true",
                        "    smtp_profile: primary_smtp",
                        "  - uid: UDI-2",
                        "    email: inactive@example.com",
                        "    is_active: false",
                        "    receives_digest: true",
                        "    smtp_profile: primary_smtp",
                        "  - uid: UDI-3",
                        "    email: wrong-profile@example.com",
                        "    is_active: true",
                        "    receives_digest: true",
                        "    smtp_profile: backup_smtp",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            recipients = resolve_recipients(
                {"to_emails": ["legacy@example.com"]},
                smtp_profile="primary_smtp",
                users_config_path=users_config,
            )
            self.assertEqual(recipients, ["active@example.com"])

    def test_resolve_recipients_falls_back_to_profile_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-users-config-missing-") as tmpdir:
            missing_users_config = Path(tmpdir) / "missing-users.yaml"
            recipients = resolve_recipients(
                {
                    "to_emails_override": ["override@example.com", "override@example.com"],
                    "to_emails": ["legacy@example.com"],
                },
                smtp_profile="primary_smtp",
                users_config_path=missing_users_config,
            )
            self.assertEqual(recipients, ["override@example.com"])


if __name__ == "__main__":
    unittest.main()
