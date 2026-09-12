"""Tests for the stdio MCP server.

Like the server itself, this module is stdlib-only -- no ``mcp`` SDK, no web
stack -- so it runs on the production host where neither is installed.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import SRC_DIR  # noqa: F401  -- puts src/ on sys.path

from bio_literature_digest.mcp.server import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    MAX_ARTIFACT_BYTES,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    build_server,
)


class MCPServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="bio-digest-mcp-")
        self.addCleanup(self.temp_dir.cleanup)
        self.run_root = Path(self.temp_dir.name) / "runs"
        self.server = build_server(self.run_root)
        self.store = self.server.service.store
        self.run_id = str(self.store.create({"skip_email": True})["id"])
        self.work_dir = self.store.run_dir(self.run_id) / "work"
        self.work_dir.mkdir(parents=True)

    # -- helpers -----------------------------------------------------------

    def call(self, method: str, params: dict | None = None, message_id: int = 1) -> dict:
        message: dict = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        response = self.server.handle_message(message)
        assert response is not None
        return response

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.call("tools/call", {"name": name, "arguments": arguments})["result"]

    @staticmethod
    def payload(result: dict) -> dict:
        return json.loads(result["content"][0]["text"])

    # -- protocol ----------------------------------------------------------

    def test_initialize_echoes_a_supported_version(self) -> None:
        requested = SUPPORTED_PROTOCOL_VERSIONS[-1]
        result = self.call("initialize", {"protocolVersion": requested})["result"]

        self.assertEqual(result["protocolVersion"], requested)
        self.assertEqual(result["capabilities"]["tools"], {"listChanged": False})
        self.assertIn("name", result["serverInfo"])

    def test_initialize_falls_back_for_unknown_version(self) -> None:
        result = self.call("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(result["protocolVersion"], SUPPORTED_PROTOCOL_VERSIONS[0])

    def test_ping_returns_empty_result(self) -> None:
        self.assertEqual(self.call("ping")["result"], {})

    def test_unknown_method_is_a_protocol_error(self) -> None:
        error = self.call("resources/list")["error"]
        self.assertEqual(error["code"], METHOD_NOT_FOUND)

    def test_notifications_are_never_answered(self) -> None:
        for method in ("notifications/initialized", "notifications/cancelled", "nonsense/method"):
            self.assertIsNone(self.server.handle_message({"jsonrpc": "2.0", "method": method}))

    def test_non_object_request_is_rejected(self) -> None:
        error = self.server.handle_message(["not", "an", "object"])["error"]
        self.assertEqual(error["code"], INVALID_REQUEST)

    def test_tools_list_advertises_read_only_surface(self) -> None:
        tools = self.call("tools/list")["result"]["tools"]
        names = sorted(tool["name"] for tool in tools)

        self.assertEqual(names, ["get_run", "list_artifacts", "list_runs", "read_artifact"])
        for tool in tools:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertTrue(tool["description"])

    def test_no_tool_can_start_a_run(self) -> None:
        advertised = {tool["name"] for tool in self.call("tools/list")["result"]["tools"]}
        self.assertEqual(advertised & {"create_run", "start_run", "run_digest"}, set())
        self.assertEqual(self.call("tools/call", {"name": "create_run"})["error"]["code"], INVALID_PARAMS)

    # -- transport ---------------------------------------------------------

    def test_serve_reads_newline_delimited_json_and_skips_blanks(self) -> None:
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            + "\n\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            + "\n"
        )
        stdout = io.StringIO()

        self.server.serve(stdin, stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]

        self.assertEqual([entry["id"] for entry in lines], [1, 2])

    def test_unparseable_line_yields_a_null_id_parse_error(self) -> None:
        stdout = io.StringIO()
        self.server.serve(io.StringIO("{oops\n"), stdout)

        response = json.loads(stdout.getvalue())

        self.assertIsNone(response["id"])
        self.assertEqual(response["error"]["code"], PARSE_ERROR)

    # -- argument validation ----------------------------------------------

    def test_missing_and_malformed_arguments_are_protocol_errors(self) -> None:
        cases = [
            ("get_run", {}),
            ("get_run", {"run_id": ""}),
            ("get_run", {"run_id": 17}),
            ("list_runs", {"limit": 0}),
            ("list_runs", {"limit": 10_000}),
            ("list_runs", {"limit": True}),
            ("list_runs", {"limit": "20"}),
            ("read_artifact", {"run_id": self.run_id, "name": "digest.csv", "max_bytes": 0}),
            (
                "read_artifact",
                {"run_id": self.run_id, "name": "digest.csv", "max_bytes": MAX_ARTIFACT_BYTES + 1},
            ),
        ]
        for name, arguments in cases:
            with self.subTest(tool=name, arguments=arguments):
                response = self.call("tools/call", {"name": name, "arguments": arguments})
                self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_non_object_arguments_are_rejected(self) -> None:
        response = self.call("tools/call", {"name": "list_runs", "arguments": [1, 2]})
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    # -- tool behaviour ----------------------------------------------------

    def test_list_runs_returns_views_newest_first(self) -> None:
        second = str(self.store.create({"skip_email": True})["id"])

        payload = self.payload(self.call_tool("list_runs", {"limit": 5}))
        ids = [entry["id"] for entry in payload["runs"]]

        self.assertEqual(set(ids), {self.run_id, second})
        self.assertIn("email_status", payload["runs"][0])
        self.assertIn("artifacts", payload["runs"][0])

    def test_list_runs_defaults_to_no_arguments(self) -> None:
        payload = self.payload(self.call_tool("list_runs", {}))
        self.assertEqual(len(payload["runs"]), 1)

    def test_get_run_reports_the_richer_status(self) -> None:
        (self.work_dir / "run_metadata.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "email_status": "failed",
                    "failed_step": "send_email",
                    "completed_steps": ["fetch_feeds"],
                    "counts": {"kept": 3},
                }
            ),
            encoding="utf-8",
        )
        self.store.update(self.run_id, status="partial_success", exit_code=6)

        payload = self.payload(self.call_tool("get_run", {"run_id": self.run_id}))

        self.assertEqual(payload["status"], "partial_success")
        self.assertEqual(payload["email_status"], "failed")
        self.assertEqual(payload["counts"], {"kept": 3})

    def test_list_artifacts_reports_sizes_and_download_paths(self) -> None:
        (self.work_dir / "digest.csv").write_text("journal,title\n", encoding="utf-8")

        payload = self.payload(self.call_tool("list_artifacts", {"run_id": self.run_id}))

        self.assertEqual(payload["artifacts"][0]["name"], "digest.csv")
        self.assertEqual(payload["artifacts"][0]["size"], len("journal,title\n"))
        self.assertEqual(
            payload["artifacts"][0]["download_url"],
            f"/api/v1/runs/{self.run_id}/artifacts/digest.csv",
        )

    def test_read_artifact_masks_subscriber_addresses(self) -> None:
        (self.store.run_dir(self.run_id) / "run.log").write_text(
            "sending to reader@example.com\n", encoding="utf-8"
        )

        payload = self.payload(
            self.call_tool("read_artifact", {"run_id": self.run_id, "name": "run.log"})
        )

        self.assertNotIn("reader@example.com", payload["text"])
        self.assertIn("r***@example.com", payload["text"])
        self.assertFalse(payload["truncated"])

    def test_read_artifact_truncates_at_the_byte_cap(self) -> None:
        (self.work_dir / "digest.csv").write_text("x" * 500, encoding="utf-8")

        payload = self.payload(
            self.call_tool(
                "read_artifact", {"run_id": self.run_id, "name": "digest.csv", "max_bytes": 10}
            )
        )

        self.assertEqual(payload["text"], "x" * 10)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["size"], 500)

    def test_read_artifact_only_advertises_text_artifacts(self) -> None:
        tool = next(
            entry for entry in self.call("tools/list")["result"]["tools"] if entry["name"] == "read_artifact"
        )
        enum = tool["inputSchema"]["properties"]["name"]["enum"]

        self.assertIn("digest.csv", enum)
        self.assertIn("run_metadata.json", enum)
        self.assertNotIn("digest.xlsx", enum)
        self.assertNotIn("status.json", enum)

    # -- tool-level failures ----------------------------------------------

    def test_unknown_run_is_an_iserror_result_not_a_protocol_error(self) -> None:
        result = self.call_tool("get_run", {"run_id": "0" * 32})

        self.assertTrue(result["isError"])
        self.assertIn("run not found", result["content"][0]["text"])

    def test_absent_artifact_is_an_iserror_result(self) -> None:
        result = self.call_tool("read_artifact", {"run_id": self.run_id, "name": "digest.csv"})

        self.assertTrue(result["isError"])
        self.assertIn("artifact not found", result["content"][0]["text"])

    def test_artifact_read_on_unknown_run_reports_the_run_not_the_artifact(self) -> None:
        result = self.call_tool("read_artifact", {"run_id": "0" * 32, "name": "digest.csv"})

        self.assertTrue(result["isError"])
        self.assertIn("run not found", result["content"][0]["text"])

    def test_successful_tool_results_are_not_flagged_as_errors(self) -> None:
        self.assertFalse(self.call_tool("list_runs", {})["isError"])


if __name__ == "__main__":
    unittest.main()
