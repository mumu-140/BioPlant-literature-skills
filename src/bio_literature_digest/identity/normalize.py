#!/usr/bin/env python3
"""Text, DOI and URL normalization used to derive stable article identity.

Moved verbatim from ``scripts/common.py`` so both ``scripts/*`` and
``src/bio_literature_digest/*`` share one implementation. Behaviour is
unchanged; ``scripts/common.py`` re-exports these names.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
}
TRACKING_QUERY_PREFIXES = ("utm_",)
DOI_PATTERN = re.compile(r"(?i)(?<![a-z0-9])10\.\d{4,9}/[-._;()/:a-z0-9]+")


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


def extract_doi(value: Any) -> str:
    """Extract and canonicalize a DOI from a field, URL, or free-form text."""

    text = normalize_whitespace(str(value or ""))
    match = DOI_PATTERN.search(text)
    if not match:
        return ""
    doi = match.group(0).rstrip(".,;:!?)]}>\"'")
    return canonicalize_doi(doi)


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
