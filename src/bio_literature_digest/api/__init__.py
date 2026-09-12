"""Remote API for launching and inspecting digest runs.

``create_app`` stays importable from this package root -- ``scripts/serve_api.py``
depends on it -- but it is resolved lazily via :pep:`562`. Importing it eagerly
would pull FastAPI into *every* ``bio_literature_digest.api.*`` import, which
would break the stdlib-only modules (``store``, ``auth``, ``configuration``,
``runs_service``) on hosts where the web stack is not installed. The MCP server
relies on that: it imports ``runs_service`` on a bare interpreter.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time only for type checkers.
    from .app import create_app

__all__ = ["create_app"]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
