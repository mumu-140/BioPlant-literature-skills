"""Article identity normalization for Bio Literature Digest.

Pure functions only: no filesystem, network, or config access. These are the
canonical implementations behind the cross-repository identity ladder
(DOI -> URL -> normalized title), and are re-exported by ``scripts/common.py``
for backwards compatibility.
"""
from __future__ import annotations

from .normalize import (
    DOI_PATTERN,
    TRACKING_QUERY_KEYS,
    TRACKING_QUERY_PREFIXES,
    canonicalize_doi,
    canonicalize_url,
    extract_doi,
    normalize_title,
    normalize_whitespace,
)

__all__ = [
    "DOI_PATTERN",
    "TRACKING_QUERY_KEYS",
    "TRACKING_QUERY_PREFIXES",
    "canonicalize_doi",
    "canonicalize_url",
    "extract_doi",
    "normalize_title",
    "normalize_whitespace",
]
