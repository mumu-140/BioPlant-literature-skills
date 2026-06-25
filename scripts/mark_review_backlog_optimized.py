#!/usr/bin/env python3
from __future__ import annotations

import sys

from review_backlog import main


if __name__ == "__main__":
    raise SystemExit(main(["mark", *sys.argv[1:]]))
