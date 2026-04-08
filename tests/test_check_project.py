#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.check_project import build_report


class CheckProjectTest(unittest.TestCase):
    def test_build_report_deduplicates_alignment_issues_and_runs_tests(self) -> None:
        with patch("scripts.check_project.build_harness_report", return_value=(["same issue"], ["h note"])):
            with patch(
                "scripts.check_project.build_alignment_report",
                return_value=(["same issue", "alignment issue"], ["a note"]),
            ):
                with patch("scripts.check_project.run_tests", return_value=(True, "Ran 3 tests\nOK")):
                    issues, notes, sections = build_report(include_tests=True)

        self.assertEqual(issues, ["same issue", "alignment issue"])
        self.assertIn("harness: h note", notes)
        self.assertIn("alignment: a note", notes)
        self.assertIn("critical tests: passed", notes)
        self.assertTrue(any("Ran 3 tests" in section for section in sections))

    def test_build_report_can_skip_tests(self) -> None:
        with patch("scripts.check_project.build_harness_report", return_value=([], [])):
            with patch("scripts.check_project.build_alignment_report", return_value=([], [])):
                issues, notes, sections = build_report(include_tests=False)

        self.assertEqual(issues, [])
        self.assertIn("critical tests: skipped by flag", notes)
        self.assertEqual(sections, [])


if __name__ == "__main__":
    unittest.main()
