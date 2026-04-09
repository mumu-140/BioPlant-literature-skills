#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


OPS_DIR = Path(__file__).resolve().parent
SKILL_DIR = OPS_DIR.parent.parent
SRC_DIR = SKILL_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bio_literature_digest.ops.imap_download import main


if __name__ == "__main__":
    raise SystemExit(main())
