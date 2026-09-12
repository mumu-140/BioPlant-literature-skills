"""Read-only MCP server exposing digest runs over JSON-RPC 2.0 on stdio.

Why hand-rolled instead of the ``mcp`` SDK: MCP's stdio transport *is*
newline-delimited JSON-RPC 2.0 on stdin/stdout. Implementing that directly
keeps this module stdlib-only, which matters because the production venv on the
deployment host has neither ``mcp`` nor the web stack installed. An SDK
dependency would make the MCP surface undeployable exactly where the runs live.

Every tool delegates to :class:`~bio_literature_digest.api.runs_service.RunsService`,
the same object the FastAPI routers use. No run inspection logic is duplicated
here; this module only translates between JSON-RPC and that service.

The surface is deliberately read-only. Starting a producer run mutates shared
state, takes the single-active-run lock and can send subscriber email, so it
stays behind the authenticated HTTP API rather than being reachable from an MCP
client with no per-caller identity.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from ..api.runs_service import (
    ARTIFACT_NAMES,
    ArtifactNotFoundError,
    RunsService,
    TEXT_ARTIFACT_SUFFIXES,
)
from ..api.store import RunStore

# Protocol revisions this server knows how to speak. The first entry is what we
# answer with when a client asks for something we do not recognise.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")

SERVER_NAME = "bio-literature-digest"
SERVER_VERSION = "1.0.0"

DEFAULT_RUN_LIMIT = 20
MAX_RUN_LIMIT = 100

DEFAULT_ARTIFACT_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024

# JSON-RPC 2.0 error codes (spec section 5.1).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    """A JSON-RPC error response carrying a spec error code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_object(params: Any) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise JsonRpcError(INVALID_PARAMS, "params must be an object")
    return params


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise JsonRpcError(INVALID_PARAMS, f"{key} must be a non-empty string")
    return value


def _bounded_int(params: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise JsonRpcError(INVALID_PARAMS, f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise JsonRpcError(INVALID_PARAMS, f"{key} must be between {minimum} and {maximum}")
    return value


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_runs",
        "description": (
            "List recent digest runs, newest first. Each entry carries the run status, "
            "email delivery status, completed pipeline steps, paper counts and available artifacts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_RUN_LIMIT,
                    "default": DEFAULT_RUN_LIMIT,
                    "description": "How many runs to return.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_run",
        "description": (
            "Inspect one digest run by id. Reports status, the step it failed at when it failed, "
            "email delivery status and the artifacts written."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "Run id as returned by list_runs."}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_artifacts",
        "description": "List the artifacts present for one run, with byte sizes and HTTP download paths.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "Run id as returned by list_runs."}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_artifact",
        "description": (
            "Read a text artifact from a run, truncated to a byte cap. Subscriber email addresses "
            "are masked. Spreadsheet exports are binary and must be fetched over HTTP instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run id as returned by list_runs."},
                "name": {
                    "type": "string",
                    "enum": sorted(
                        name
                        for name in ARTIFACT_NAMES
                        if Path(name).suffix.lower() in TEXT_ARTIFACT_SUFFIXES
                    ),
                    "description": "Artifact filename.",
                },
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_ARTIFACT_BYTES,
                    "default": DEFAULT_ARTIFACT_BYTES,
                    "description": "Byte cap on the returned text.",
                },
            },
            "required": ["run_id", "name"],
            "additionalProperties": False,
        },
    },
]


class MCPServer:
    """Translate MCP JSON-RPC calls into :class:`RunsService` reads."""

    def __init__(self, service: RunsService) -> None:
        self.service = service
        self.protocol_version = SUPPORTED_PROTOCOL_VERSIONS[0]
        self._methods: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "initialize": self._initialize,
            "ping": lambda params: {},
            "tools/list": self._tools_list,
            "tools/call": self._tools_call,
        }
        self._tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            "list_runs": self._tool_list_runs,
            "get_run": self._tool_get_run,
            "list_artifacts": self._tool_list_artifacts,
            "read_artifact": self._tool_read_artifact,
        }

    # -- JSON-RPC plumbing -------------------------------------------------

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        """Dispatch one decoded message. Returns ``None`` for notifications."""
        if not isinstance(message, dict):
            return self._error_response(None, INVALID_REQUEST, "request must be an object")

        message_id = message.get("id")
        is_notification = "id" not in message
        method = message.get("method")

        if not isinstance(method, str) or not method:
            if is_notification:
                return None
            return self._error_response(message_id, INVALID_REQUEST, "method must be a non-empty string")

        handler = self._methods.get(method)
        if handler is None:
            # Unknown notifications are dropped: the spec forbids answering them,
            # and clients legitimately send ones we do not implement
            # (notifications/initialized, notifications/cancelled).
            if is_notification:
                return None
            return self._error_response(message_id, METHOD_NOT_FOUND, f"unknown method: {method}")

        try:
            result = handler(_require_object(message.get("params")))
        except JsonRpcError as exc:
            if is_notification:
                return None
            return self._error_response(message_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - a bad request must not kill the server.
            if is_notification:
                return None
            return self._error_response(message_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    @staticmethod
    def _error_response(message_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        """Read newline-delimited JSON-RPC from ``stdin`` until EOF."""
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # No id is recoverable from unparseable input, so the spec's
                # null-id parse error is the only correct answer.
                self._write(stdout, self._error_response(None, PARSE_ERROR, "invalid JSON"))
                continue
            response = self.handle_message(message)
            if response is not None:
                self._write(stdout, response)

    @staticmethod
    def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stdout.flush()

    # -- MCP methods -------------------------------------------------------

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
            self.protocol_version = requested
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": TOOL_DEFINITIONS}

    def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = _require_str(params, "name")
        tool = self._tools.get(name)
        if tool is None:
            raise JsonRpcError(INVALID_PARAMS, f"unknown tool: {name}")
        arguments = _require_object(params.get("arguments"))
        try:
            payload = tool(arguments)
        except JsonRpcError:
            raise
        except (KeyError, ArtifactNotFoundError) as exc:
            # Tool-level failures belong in the result as isError, not as a
            # protocol error: the call itself was well-formed.
            return self._tool_error(f"{_not_found_label(exc)}: {exc}")
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "isError": False,
        }

    @staticmethod
    def _tool_error(message: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": message}], "isError": True}

    # -- tools -------------------------------------------------------------

    def _tool_list_runs(self, arguments: dict[str, Any]) -> Any:
        limit = _bounded_int(arguments, "limit", DEFAULT_RUN_LIMIT, 1, MAX_RUN_LIMIT)
        return {"runs": self.service.views(self.service.list_recent(limit))}

    def _tool_get_run(self, arguments: dict[str, Any]) -> Any:
        run_id = _require_str(arguments, "run_id")
        return self.service.view(self.service.get(run_id))

    def _tool_list_artifacts(self, arguments: dict[str, Any]) -> Any:
        run_id = _require_str(arguments, "run_id")
        self.service.get(run_id)
        return {"artifacts": self.service.artifacts(run_id)}

    def _tool_read_artifact(self, arguments: dict[str, Any]) -> Any:
        run_id = _require_str(arguments, "run_id")
        name = _require_str(arguments, "name")
        max_bytes = _bounded_int(
            arguments, "max_bytes", DEFAULT_ARTIFACT_BYTES, 1, MAX_ARTIFACT_BYTES
        )
        self.service.get(run_id)
        return self.service.read_text_artifact(run_id, name, max_bytes)


def _not_found_label(exc: Exception) -> str:
    return "artifact not found" if isinstance(exc, ArtifactNotFoundError) else "run not found"


def build_server(run_root: Path) -> MCPServer:
    """Build a server reading the run store at ``run_root``."""
    return MCPServer(RunsService(RunStore(run_root)))


def main(run_root: Path) -> int:
    """Serve MCP on stdio against the run store at ``run_root``."""
    build_server(run_root).serve(sys.stdin, sys.stdout)
    return 0
