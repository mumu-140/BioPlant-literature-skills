#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_harness import build_report


class HarnessTest(unittest.TestCase):
    def test_harness_flags_sensitive_literals_and_generated_plist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-harness-") as tmpdir:
            root = Path(tmpdir)
            for path in [
                root / "config" / "content",
                root / "config" / "integrations",
                root / "config" / "runtime",
                root / "local",
                root / "var",
                root / "docs",
                root / "ops" / "launchd",
                root / "scripts",
            ]:
                path.mkdir(parents=True, exist_ok=True)

            (root / "config" / "env.local.example").write_text("SMTP_APP_PASSWORD=\n", encoding="utf-8")
            (root / "docs" / "engineering_harness.md").write_text("# harness\n", encoding="utf-8")
            (root / "ops" / "launchd" / "bio-digest-daily.plist.template").write_text("template\n", encoding="utf-8")
            (root / "ops" / "launchd" / "bio-digest-daily.plist").write_text("generated\n", encoding="utf-8")
            email_literal = "real.user" + "@" + "qq.com"
            path_literal = "/" + "Users/" + "someone/private"
            label_literal = "com" + "." + "private-team" + ".demo"
            (root / "scripts" / "bad.py").write_text(
                f"EMAIL='{email_literal}'\nPATH='{path_literal}'\nLABEL='{label_literal}'\n",
                encoding="utf-8",
            )

            issues, _ = build_report(root)
            joined = "\n".join(issues)
            self.assertIn("真实邮箱", joined)
            self.assertIn("个人路径", joined)
            self.assertIn("个人化 scheduler label", joined)
            self.assertIn("生成型 plist", joined)


if __name__ == "__main__":
    unittest.main()
