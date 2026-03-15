#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from html import unescape
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
}
TRACKING_QUERY_PREFIXES = ("utm_",)


def ensure_parent_dir(path: str | Path) -> Path:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    return path_obj


def load_yaml_file(path: str | Path) -> Any:
    path_obj = Path(path)
    try:
        import yaml  # type: ignore

        with path_obj.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except ModuleNotFoundError:
        command = [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "print JSON.dump(YAML.load_file(ARGV[0]))",
            str(path_obj),
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    path_obj = ensure_parent_dir(path)
    with path_obj.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    cleaned = unescape(value)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_title(value: str | None) -> str:
    cleaned = normalize_whitespace(value).lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return cleaned.strip()


def canonicalize_doi(value: str | None) -> str:
    if not value:
        return ""
    doi = normalize_whitespace(value)
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().lower()


def canonicalize_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip()
    filtered_query = []
    for key, raw_value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in TRACKING_QUERY_KEYS or any(key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        filtered_query.append((key, raw_value))
    clean_path = parsed.path or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            "",
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


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


def count_nonempty_fields(record: dict[str, Any]) -> int:
    score = 0
    for value in record.values():
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            score += 1
        elif isinstance(value, (list, dict)) and value:
            score += 1
        elif not isinstance(value, (str, list, dict)):
            score += 1
    return score


def keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for keyword in keywords:
        key = keyword.lower()
        escaped = re.escape(key)
        escaped = escaped.replace(r"\ ", r"\s+")
        if re.fullmatch(r"[a-z][a-z0-9-]{2,}", key) and not key.endswith("s"):
            escaped = escaped + r"s?"
        pattern = escaped
        if key[:1].isalnum():
            pattern = r"(?<![a-z0-9])" + pattern
        if key[-1:].isalnum():
            pattern = pattern + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            hits.append(keyword)
    return hits


def safe_text_join(parts: Iterable[Any]) -> str:
    values = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            values.extend(str(item) for item in part if item)
        else:
            values.append(str(part))
    return normalize_whitespace(" ".join(values))


def load_watchlist(path: str | Path) -> dict[str, Any]:
    data = load_yaml_file(path) or {}
    journals = data.get("journals", [])
    by_id = {journal["id"]: journal for journal in journals if "id" in journal}
    by_name = {journal["journal_name"]: journal for journal in journals if "journal_name" in journal}
    data["by_id"] = by_id
    data["by_name"] = by_name
    return data


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
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    current_utc = now_utc or datetime.now(timezone.utc)
    local_now = current_utc.astimezone(tz)
    hour, minute = parse_clock_hhmm(delivery_time)
    anchor = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now < anchor:
        end_local = anchor - timedelta(days=1)
    else:
        end_local = anchor
    start_local = end_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def within_utc_window(value: datetime | None, window_start: datetime | None, window_end: datetime | None) -> bool:
    if value is None:
        return False
    if window_start is not None and value < window_start:
        return False
    if window_end is not None and value > window_end:
        return False
    return True
