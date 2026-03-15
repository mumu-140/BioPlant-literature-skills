#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.send_email import build_message


class SendEmailTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
