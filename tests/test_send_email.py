#!/usr/bin/env python3
"""Unified tests for scripts/send_email.py.

Merged from:
  - test_send_email.py (build_message)
  - test_send_email_recipients.py (resolve_recipients)
"""
from __future__ import annotations

import tempfile
import csv
import unittest
from pathlib import Path
from unittest import mock
import smtplib

from scripts.send_email import (
    build_message, render_agently_digest_preview, render_agently_html_body,
    resolve_recipients, send_digest_email,
)


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


class AgentlyMailHTMLRegressionTest(unittest.TestCase):
    def test_full_html_document_becomes_styled_body_fragment(self) -> None:
        html_document = (
            '<!DOCTYPE html><html lang="zh-CN"><head><style>'
            '.card { color: #123456; background: #eef6ef; }'
            '</style></head><body><div class="card">'
            '<strong>中文标题</strong><a href="https://example.org/paper?a=1&amp;b=2">查看</a>'
            '<details><summary>英文摘要</summary><p>Abstract content</p></details>'
            '<script>window.bad = 1</script></div></body></html>'
        )
        fragment = render_agently_html_body(html_document)
        self.assertTrue(fragment.startswith("<div"))
        self.assertNotIn("<!DOCTYPE", fragment)
        self.assertNotIn("<html", fragment)
        self.assertNotIn("<head", fragment)
        self.assertNotIn("<script", fragment)
        self.assertNotIn("<details", fragment)
        self.assertNotIn("<summary", fragment)
        self.assertIn("Abstract content", fragment)
        self.assertNotIn("&lt;strong", fragment)
        self.assertIn("<strong>", fragment)
        self.assertIn("中文标题", fragment)
        self.assertIn("color:#123456", fragment)
        self.assertIn("https://example.org/paper?a=1&amp;b=2", fragment)

    def test_oversized_inlined_html_uses_non_inlined_fragment(self) -> None:
        source = "<html><body><p>Full report intact</p></body></html>"
        oversized = "<html><body><p style='" + ("x" * 920_000) + "'>Large</p></body></html>"
        with mock.patch("scripts.send_email.transform", return_value=oversized):
            fragment = render_agently_html_body(source)
        self.assertIn("Full report intact", fragment)
        self.assertNotIn("<html", fragment)
        self.assertLess(len(fragment.encode("utf-8")), 900_000)


    def test_compact_preview_all_papers_keep_links_and_summaries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-mail-preview-") as tmp:
            csv_path = Path(tmp) / "digest.csv"
            columns = ["title_en", "title_zh", "article_url", "journal", "category", "summary_zh"]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for i in range(142):
                    writer.writerow({
                        "title_en": f"Original paper {i}",
                        "title_zh": f"中文标题{i}",
                        "article_url": f"https://example.org/paper/{i}?a=1&b=2",
                        "journal": "Nature",
                        "category": "分子生物学",
                        "summary_zh": (
                            "当前未配置自动中文翻译模型"
                            if i == 0 else f"中文摘要内容{i}"
                        ),
                    })
            preview = render_agently_digest_preview(csv_path, "Bio Digest Through 2026-11-16")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.count("<li "), 142)
        self.assertEqual(preview.count("https://example.org/paper/"), 142)
        self.assertLess(preview.count("<li "), 150)
        self.assertIn("中文摘要内容1", preview)
        self.assertNotIn("当前未配置自动中文翻译模型", preview)
        self.assertIn("https://example.org/paper/1?a=1&amp;b=2", preview)
        self.assertNotIn("<html", preview)
        self.assertNotIn("&lt;li", preview)
        self.assertLess(len(preview.encode("utf-8")), 200_000)

    def test_excessive_dom_nodes_fall_back_to_safe_link_cover(self) -> None:
        oversized = "<html><body>" + "<span>paper</span>" * 600 + "</body></html>"
        result = render_agently_html_body(oversized)
        self.assertIn("accept.yangsen666.cloud/papers/published", result)
        self.assertLess(result.count("<span"), 10)
        self.assertNotIn("<html", result)


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

    def test_send_digest_email_continues_after_permanent_recipient_failure(self) -> None:
        sent: list[str] = []

        class FakeSMTP:
            def __init__(self, host: str, port: int) -> None:
                self.host = host
                self.port = port

            def __enter__(self) -> "FakeSMTP":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
                return None

            def login(self, username: str, password: str) -> None:
                self.username = username
                self.password = password

            def send_message(self, message) -> dict[str, object]:  # type: ignore[no-untyped-def]
                recipient = message["To"]
                if recipient == "blocked@example.com":
                    raise smtplib.SMTPDataError(550, b"sender is blacklisted")
                sent.append(recipient)
                return {}

        with tempfile.TemporaryDirectory(prefix="bio-send-email-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            email_config = tmpdir_path / "email.yaml"
            users_config = tmpdir_path / "users.yaml"
            html_path = tmpdir_path / "digest.html"
            csv_path = tmpdir_path / "digest.csv"
            xlsx_path = tmpdir_path / "digest.xlsx"
            email_config.write_text(
                "\n".join(
                    [
                        "smtp_profiles:",
                        "  primary_smtp:",
                        "    smtp_host: smtp.example.com",
                        "    smtp_port: 465",
                        "    security: ssl",
                        "    username: sender@example.com",
                        "    from_email: sender@example.com",
                        "    from_name: Sender",
                        "    password_env: SMTP_PASSWORD",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            users_config.write_text(
                "\n".join(
                    [
                        "users:",
                        "  - email: first@example.com",
                        "    is_active: true",
                        "    receives_digest: true",
                        "    smtp_profile: primary_smtp",
                        "  - email: blocked@example.com",
                        "    is_active: true",
                        "    receives_digest: true",
                        "    smtp_profile: primary_smtp",
                        "  - email: later@example.com",
                        "    is_active: true",
                        "    receives_digest: true",
                        "    smtp_profile: primary_smtp",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            html_path.write_text("<html><body>Hi</body></html>", encoding="utf-8")
            csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
            xlsx_path.write_bytes(b"fake-xlsx")

            with mock.patch.dict("os.environ", {"SMTP_PASSWORD": "secret"}):
                with mock.patch("scripts.send_email.smtplib.SMTP_SSL", FakeSMTP):
                    with self.assertRaises(SystemExit):
                        send_digest_email(
                            config_path=email_config,
                            profile_name="primary_smtp",
                            html_body_path=html_path,
                            csv_attachment_path=csv_path,
                            xlsx_attachment_path=xlsx_path,
                            subject="Test",
                            users_config=users_config,
                            max_attempts=1,
                        )

        self.assertEqual(sent, ["first@example.com", "later@example.com"])

    def test_send_digest_email_uses_agently_confirmation_flow(self) -> None:
        calls: list[list[str]] = []
        written_bodies: list[str] = []

        def fake_run(args, cwd, text, capture_output, check):  # type: ignore[no-untyped-def]
            calls.append(list(args))
            written_bodies.append((Path(cwd) / args[args.index("--body-file") + 1]).read_text())
            if "--confirmation-token" in args:
                stdout = '{"ok": true, "data": {"queued": true}}\n'
            else:
                stdout = '{"data": {"confirmation_required": true, "confirmation_token": "ctk_test"}}\n'
            return mock.Mock(returncode=0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory(prefix="bio-agently-email-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            email_config = tmpdir_path / "email.yaml"
            users_config = tmpdir_path / "users.yaml"
            html_path = tmpdir_path / "digest.html"
            csv_path = tmpdir_path / "digest.csv"
            xlsx_path = tmpdir_path / "digest.xlsx"
            email_config.write_text(
                "\n".join(
                    [
                        "agently_profiles:",
                        "  agent_mail:",
                        "    cli_bin: agently-cli",
                        "    users_profile: qq_mail",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            users_config.write_text(
                "\n".join(
                    [
                        "users:",
                        "  - email: first@example.com",
                        "    is_active: true",
                        "    receives_digest: true",
                        "    smtp_profile: qq_mail",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            html_path.write_text("<!DOCTYPE html><html><head><style>p{color:#123456}</style></head><body><p>Hi</p></body></html>", encoding="utf-8")
            csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
            xlsx_path.write_bytes(b"fake-xlsx")

            with mock.patch("scripts.send_email.subprocess.run", fake_run):
                sent = send_digest_email(
                    config_path=email_config,
                    profile_name="agent_mail",
                    html_body_path=html_path,
                    csv_attachment_path=csv_path,
                    xlsx_attachment_path=xlsx_path,
                    subject="Test",
                    users_config=users_config,
                )

        self.assertEqual(sent, ["first@example.com"])
        self.assertEqual(len(calls), 2)
        self.assertIn("--confirmation-token", calls[1])
        self.assertIn("ctk_test", calls[1])
        self.assertEqual(len(written_bodies), 2)
        self.assertTrue(all(body.startswith("<div") for body in written_bodies))
        self.assertTrue(all("<!DOCTYPE" not in body and "<html" not in body for body in written_bodies))
        self.assertTrue(all('style="color:#123456"' in body for body in written_bodies))

    def test_agently_failure_without_fallback_does_not_send_smtp(self) -> None:
        def fake_run(args, cwd, text, capture_output, check):  # type: ignore[no-untyped-def]
            return mock.Mock(returncode=1, stdout="", stderr="network error")

        with tempfile.TemporaryDirectory(prefix="bio-agently-no-fallback-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            email_config = tmpdir_path / "email.yaml"
            users_config = tmpdir_path / "users.yaml"
            html_path = tmpdir_path / "digest.html"
            csv_path = tmpdir_path / "digest.csv"
            xlsx_path = tmpdir_path / "digest.xlsx"
            email_config.write_text(
                "\n".join(
                    [
                        "agently_profiles:",
                        "  agent_mail:",
                        "    cli_bin: agently-cli",
                        "    users_profile: qq_mail",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            users_config.write_text(
                "\n".join(
                    [
                        "users:",
                        "  - email: first@example.com",
                        "    is_active: true",
                        "    receives_digest: true",
                        "    smtp_profile: qq_mail",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            html_path.write_text("<html><body>Hi</body></html>", encoding="utf-8")
            csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
            xlsx_path.write_bytes(b"fake-xlsx")

            with mock.patch("scripts.send_email.subprocess.run", fake_run):
                with mock.patch("scripts.send_email.smtplib.SMTP_SSL") as smtp_ssl:
                    with self.assertRaises(SystemExit):
                        send_digest_email(
                            config_path=email_config,
                            profile_name="agent_mail",
                            html_body_path=html_path,
                            csv_attachment_path=csv_path,
                            xlsx_attachment_path=xlsx_path,
                            subject="Test",
                            users_config=users_config,
                            max_attempts=1,
                        )

        smtp_ssl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
