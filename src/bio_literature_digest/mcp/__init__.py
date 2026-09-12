"""Model Context Protocol surface over the shared run service.

The server lives in :mod:`bio_literature_digest.mcp.server` and is imported
lazily for the same reason the HTTP API is: nothing here may drag optional
dependencies into an import of the package root.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time only for type checkers.
    from .server import MCPServer, build_server

__all__ = ["MCPServer", "build_server"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
