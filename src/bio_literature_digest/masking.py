"""Mask subscriber addresses before they reach operator-visible logs.

This is deliberately separate from :mod:`bio_literature_digest.ai.redaction`.
That module prepares text for LLM prompts and also strips URLs, filesystem
paths and whitespace, which destroys the diagnostic value of a run log. Here
only email addresses are masked, so operators keep every other detail.
"""
from __future__ import annotations

import re
from typing import Iterable


EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def mask_email(value: str) -> str:
    """Mask the local part of an address, keeping the domain for triage."""
    text = (value or "").strip()
    if not text:
        return ""
    local, separator, domain = text.partition("@")
    if not separator or not domain or not local:
        return "[redacted-email]"
    return f"{local[:1]}***@{domain}"


def mask_emails(values: Iterable[str]) -> list[str]:
    """Mask every address in an iterable, preserving order."""
    return [mask_email(value) for value in values]


def mask_email_list(values: Iterable[str]) -> str:
    """Render a masked, comma-separated address list for log lines."""
    return ", ".join(mask_emails(values))


def mask_email_text(value: str) -> str:
    """Mask addresses embedded in free text, leaving everything else intact."""
    return EMAIL_PATTERN.sub(lambda match: mask_email(match.group(0)), value or "")
