#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common import keyword_hits


class CommonKeywordTest(unittest.TestCase):
    def test_keyword_hits_respects_word_boundaries(self) -> None:
        text = "Cellulose-based sensors enable single-cell profiling."
        hits = keyword_hits(text, ["cell", "single-cell", "sensors"])
        self.assertEqual(hits, ["cell", "single-cell", "sensors"])


if __name__ == "__main__":
    unittest.main()
