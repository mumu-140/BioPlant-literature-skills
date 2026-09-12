#!/usr/bin/env python3
"""Serve the read-only MCP surface over stdio.

Register with an MCP client as::

    {"command": "python3", "args": ["<skill_dir>/scripts/serve_mcp.py"]}

Two things differ from ``serve_api.py`` on purpose:

* ``local/.env.local`` is loaded only when it exists. The MCP surface is
  read-only over the run store, so it needs no provider credentials and must
  not refuse to start on a host that has none.
* Nothing may be printed to stdout. Stdout *is* the JSON-RPC channel, so any
  stray write corrupts the stream; diagnostics go to stderr.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from _bootstrap import SKILL_DIR
from with_env import load_env_file

_env_file = Path(os.environ.get("BIO_DIGEST_ENV_FILE", str(SKILL_DIR / "local" / ".env.local")))
if _env_file.is_file():
    load_env_file(_env_file)

from bio_literature_digest.mcp.server import main as serve_stdio  # noqa: E402


def default_run_root() -> Path:
    """Resolve the run store the same way :func:`create_app` does."""
    return Path(
        os.environ.get("BIO_DIGEST_API_RUN_ROOT", str(SKILL_DIR / "var" / "api" / "runs"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Bio Literature Digest MCP server on stdio.")
    parser.add_argument(
        "--run-root",
        type=Path,
        default=default_run_root(),
        help="Run store directory (default: $BIO_DIGEST_API_RUN_ROOT or var/api/runs).",
    )
    args = parser.parse_args()
    return serve_stdio(args.run_root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
