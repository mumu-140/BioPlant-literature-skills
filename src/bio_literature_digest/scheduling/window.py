#!/usr/bin/env python3
"""Timestamp parsing and scheduled digest window computation.

Moved verbatim from ``scripts/common.py`` so both ``scripts/*`` and
``src/bio_literature_digest/*`` share one implementation. Behaviour is
unchanged; ``scripts/common.py`` re-exports these names.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from ..identity.normalize import normalize_whitespace


def parse_datetime_guess(value: str | None) -> datetime | None:
    if not value:
        return None
    text = normalize_whitespace(value)
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text.replace("Z", "+00:00"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def isoformat_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_timestamp_utc() -> str:
    return isoformat_utc(datetime.now(timezone.utc))


def parse_clock_hhmm(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.strip().split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid HH:MM value: {value}")
    return hour, minute


def compute_scheduled_digest_window(
    timezone_name: str,
    delivery_time: str,
    now_utc: datetime | None = None,
    window_policy: str = "previous_day",
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    current_utc = now_utc or datetime.now(timezone.utc)
    local_now = current_utc.astimezone(tz)
    hour, minute = parse_clock_hhmm(delivery_time)
    anchor = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delivery_date = local_now.date() if local_now >= anchor else (local_now.date() - timedelta(days=1))

    if window_policy == "previous_day":
        start_local = datetime.combine(delivery_date - timedelta(days=1), time(0, 0), tzinfo=tz)
        end_local = datetime.combine(delivery_date, time(0, 0), tzinfo=tz)
    elif window_policy == "previous_day_to_delivery":
        start_local = datetime.combine(delivery_date - timedelta(days=1), time(0, 0), tzinfo=tz)
        end_local = datetime.combine(delivery_date, time(hour, minute), tzinfo=tz)
    else:
        raise ValueError(f"Unsupported window_policy: {window_policy}")
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def within_utc_window(value: datetime | None, window_start: datetime | None, window_end: datetime | None) -> bool:
    if value is None:
        return False
    if window_start is not None and value < window_start:
        return False
    if window_end is not None and value > window_end:
        return False
    return True
