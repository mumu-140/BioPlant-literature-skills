#!/usr/bin/env python3
from __future__ import annotations

import sys

from optimization_reports import main as optimization_reports_main


# Deprecated compatibility wrapper. Prefer:
#   python3 scripts/optimization_reports.py glossary-candidates ...
def main() -> int:
    return optimization_reports_main(["glossary-candidates", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
