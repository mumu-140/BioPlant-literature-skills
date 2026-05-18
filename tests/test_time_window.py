#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.common import compute_scheduled_digest_window, isoformat_utc


class ScheduledWindowPolicyTest(unittest.TestCase):
    def test_previous_day_policy_uses_previous_local_calendar_day(self) -> None:
        now_utc = datetime(2026, 4, 10, 0, 30, tzinfo=timezone.utc)
        window_start, window_end = compute_scheduled_digest_window(
            "Asia/Shanghai",
            "08:00",
            now_utc=now_utc,
            window_policy="previous_day",
        )

        self.assertEqual(isoformat_utc(window_start), "2026-04-08T16:00:00Z")
        self.assertEqual(isoformat_utc(window_end), "2026-04-09T16:00:00Z")

    def test_previous_day_to_delivery_policy_keeps_legacy_schedule_span(self) -> None:
        now_utc = datetime(2026, 4, 10, 0, 30, tzinfo=timezone.utc)
        window_start, window_end = compute_scheduled_digest_window(
            "Asia/Shanghai",
            "08:00",
            now_utc=now_utc,
            window_policy="previous_day_to_delivery",
        )

        self.assertEqual(isoformat_utc(window_start), "2026-04-08T16:00:00Z")
        self.assertEqual(isoformat_utc(window_end), "2026-04-10T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
