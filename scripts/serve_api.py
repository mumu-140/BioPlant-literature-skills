#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from _bootstrap import SKILL_DIR
from with_env import load_env_file

load_env_file(Path(os.environ.get("BIO_DIGEST_ENV_FILE", str(SKILL_DIR / "local" / ".env.local"))))

from bio_literature_digest.api import create_app  # noqa: E402


app = create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Bio Literature Digest remote API.")
    parser.add_argument("--host", default=os.environ.get("BIO_DIGEST_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BIO_DIGEST_API_PORT", "8787")))
    parser.add_argument("--log-level", default=os.environ.get("BIO_DIGEST_API_LOG_LEVEL", "info"))
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
