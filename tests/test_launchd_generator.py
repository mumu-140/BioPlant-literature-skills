#!/usr/bin/env python3
from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path

from scripts.generate_launchd_plist import render_launchd_plist


class LaunchdGeneratorTest(unittest.TestCase):
    def test_render_launchd_plist_uses_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-launchd-") as tmpdir:
            root = Path(tmpdir)
            runtime_config = root / "production.yaml"
            template = root / "job.plist.template"
            template.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>__LABEL__</string>
  <key>ProgramArguments</key>
  <array><string>__WRAPPER_SCRIPT__</string></array>
  <key>WorkingDirectory</key>
  <string>__WORKING_DIRECTORY__</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>__HOUR__</integer><key>Minute</key><integer>__MINUTE__</integer></dict>
  <key>StandardOutPath</key>
  <string>__STDOUT_LOG__</string>
  <key>StandardErrorPath</key>
  <string>__STDERR_LOG__</string>
</dict>
</plist>
""",
                encoding="utf-8",
            )
            runtime_config.write_text(
                """
delivery:
  delivery_time: "09:30"

scheduler:
  launchd:
    label: com.example.digest
    wrapper_script: /tmp/example/run.sh
    working_directory: /tmp/example
    stdout_log: /tmp/example/stdout.log
    stderr_log: /tmp/example/stderr.log
""".strip()
                + "\n",
                encoding="utf-8",
            )

            content = render_launchd_plist(runtime_config, template)
            payload = plistlib.loads(content.encode("utf-8"))
            self.assertEqual(payload["Label"], "com.example.digest")
            self.assertEqual(payload["ProgramArguments"][0], "/tmp/example/run.sh")
            self.assertEqual(payload["WorkingDirectory"], "/tmp/example")
            self.assertEqual(payload["StartCalendarInterval"]["Hour"], 9)
            self.assertEqual(payload["StartCalendarInterval"]["Minute"], 30)
            self.assertEqual(payload["StandardOutPath"], "/tmp/example/stdout.log")
            self.assertEqual(payload["StandardErrorPath"], "/tmp/example/stderr.log")


if __name__ == "__main__":
    unittest.main()
