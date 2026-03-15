#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"


class WithEnvTest(unittest.TestCase):
    def test_with_env_loads_variables_and_runs_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bio-with-env-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            env_file = tmpdir_path / ".env.local"
            env_file.write_text("EXAMPLE_TOKEN=hello_world\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "with_env.py"),
                    "--env-file",
                    str(env_file),
                    "--",
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('EXAMPLE_TOKEN', ''))",
                ],
                check=True,
                cwd=SKILL_DIR,
                capture_output=True,
                text=True,
            )
            self.assertIn("hello_world", completed.stdout)


if __name__ == "__main__":
    unittest.main()
