#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        raise FileNotFoundError(
            f"Env file not found: {env_path}\n"
            f"Copy {SKILL_DIR / '.env.local.example'} to {SKILL_DIR / '.env.local'} and fill the values."
        )
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load .env.local and run a command, with automatic OS detection.")
    parser.add_argument("--env-file", default=str(SKILL_DIR / ".env.local"), help="Path to .env file")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after loading env. Use -- before the command.")
    args = parser.parse_args()

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("No command provided. Example: python3 scripts/with_env.py -- python3 scripts/run_digest.py ...")

    env_path = Path(args.env_file).resolve()
    load_env_file(env_path)
    system_name = platform.system() or "Unknown"
    print(f"[with_env] detected system: {system_name}")
    print(f"[with_env] loaded: {env_path}")
    completed = subprocess.run(command)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
