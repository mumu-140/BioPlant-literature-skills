"""Tests for the framework-free run service shared by the API and MCP.

Deliberately imports no web stack: this module must stay runnable on the
production host, where fastapi and pydantic are not installed.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import SRC_DIR  # noqa: F401  -- puts src/ on sys.path

from bio_literature_digest.api.runs_service import (
    ArtifactNotFoundError,
    RunsService,
    resolve_outcome,
    summarize_metadata,
)
from bio_literature_digest.api.store import RunStore


class ResolveOutcomeTest(unittest.TestCase):
    """The four outcomes the old ``returncode == 0 and status == success`` test
    collapsed into a bare ``failed`` with an empty message."""

    def test_success_requires_both_signals(self) -> None:
        status, message = resolve_outcome(exit_code=0, metadata={"status": "success"})
        self.assertEqual(status, "success")
        self.assertEqual(message, "")

    def test_metadata_success_with_nonzero_exit_is_a_failure(self) -> None:
        status, message = resolve_outcome(exit_code=3, metadata={"status": "success"})
        self.assertEqual(status, "failed")
        self.assertIn("exited with code 3", message)

    def test_delivery_failure_is_partial_success(self) -> None:
        status, message = resolve_outcome(
            exit_code=6,
            metadata={
                "status": "failed",
                "failed_step": "send_email",
                "failure_message": "agently-cli send failed with exit 6",
            },
        )
        self.assertEqual(status, "partial_success")
        self.assertEqual(message, "agently-cli send failed with exit 6")

    def test_earlier_step_failure_stays_failed(self) -> None:
        status, message = resolve_outcome(
            exit_code=1, metadata={"status": "failed", "failed_step": "fetch_feeds"}
        )
        self.assertEqual(status, "failed")
        self.assertIn("fetch_feeds", message)

    def test_missing_metadata_is_reported_not_swallowed(self) -> None:
        clean_exit, clean_message = resolve_outcome(exit_code=0, metadata={})
        crash, crash_message = resolve_outcome(exit_code=9, metadata={})
        self.assertEqual(clean_exit, "failed")
        self.assertIn("exited 0 without writing", clean_message)
        self.assertEqual(crash, "failed")
        self.assertIn("code 9", crash_message)


class SummarizeMetadataTest(unittest.TestCase):
    def test_email_status_is_propagated_never_recomputed(self) -> None:
        summary = summarize_metadata({"email_status": "skipped", "completed_steps": ["send_email"]})
        self.assertEqual(summary["email_status"], "skipped")

    def test_absent_fields_become_empty_not_missing(self) -> None:
        summary = summarize_metadata({})
        self.assertEqual(
            summary,
            {
                "email_status": "",
                "failed_step": "",
                "failure_type": "",
                "completed_steps": [],
                "counts": {},
            },
        )

    def test_malformed_shapes_are_dropped_without_raising(self) -> None:
        summary = summarize_metadata(
            {"completed_steps": "fetch_feeds", "counts": {"kept": 4, "ratio": 0.5, "flag": True}}
        )
        self.assertEqual(summary["completed_steps"], [])
        self.assertEqual(summary["counts"], {"kept": 4})


class RunsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="bio-digest-service-")
        self.addCleanup(self.temp_dir.cleanup)
        self.store = RunStore(Path(self.temp_dir.name) / "runs")
        self.service = RunsService(self.store)
        self.run_id = str(self.store.create({"skip_email": True})["id"])
        self.work_dir = self.store.run_dir(self.run_id) / "work"
        self.work_dir.mkdir(parents=True)

    def write_artifact(self, name: str, text: str) -> None:
        (self.work_dir / name).write_text(text, encoding="utf-8")

    def test_unknown_run_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            self.service.get("0" * 32)

    def test_only_allow_listed_present_files_are_listed(self) -> None:
        self.write_artifact("digest.csv", "journal,title\n")
        self.write_artifact("secrets.env", "TOKEN=x\n")
        (self.store.run_dir(self.run_id) / "run.log").write_text("started\n", encoding="utf-8")

        names = [entry["name"] for entry in self.service.artifacts(self.run_id)]

        self.assertEqual(names, ["digest.csv", "run.log"])

    def test_artifact_path_rejects_traversal_and_bookkeeping(self) -> None:
        for name in ("../status.json", "status.json", "secrets.env"):
            with self.assertRaises(ArtifactNotFoundError):
                self.service.artifact_path(self.run_id, name)

    def test_binary_artifact_cannot_be_read_as_text(self) -> None:
        (self.work_dir / "digest.xlsx").write_bytes(b"PK\x03\x04")
        with self.assertRaises(ArtifactNotFoundError):
            self.service.read_text_artifact(self.run_id, "digest.xlsx", 1024)

    def test_read_text_artifact_masks_addresses_and_reports_truncation(self) -> None:
        # run.log is the one artifact that lives at the run root, not in work/.
        (self.store.run_dir(self.run_id) / "run.log").write_text(
            "delivered to reader@example.com\n", encoding="utf-8"
        )

        full = self.service.read_text_artifact(self.run_id, "run.log", 4096)
        capped = self.service.read_text_artifact(self.run_id, "run.log", 8)

        self.assertNotIn("reader@example.com", full["text"])
        self.assertIn("r***@example.com", full["text"])
        self.assertFalse(full["truncated"])
        self.assertTrue(capped["truncated"])
        self.assertEqual(capped["size"], full["size"])

    def test_view_merges_store_record_with_live_metadata(self) -> None:
        (self.work_dir / "run_metadata.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "email_status": "failed",
                    "failed_step": "send_email",
                    "failure_type": "delivery",
                    "completed_steps": ["fetch_feeds", "export_digest"],
                    "counts": {"kept": 12},
                }
            ),
            encoding="utf-8",
        )
        self.write_artifact("digest.html", "<html></html>")
        self.store.update(self.run_id, status="partial_success", exit_code=6)

        view = self.service.view(self.service.get(self.run_id))

        self.assertEqual(view["status"], "partial_success")
        self.assertEqual(view["exit_code"], 6)
        self.assertEqual(view["email_status"], "failed")
        self.assertEqual(view["failed_step"], "send_email")
        self.assertEqual(view["completed_steps"], ["fetch_feeds", "export_digest"])
        self.assertEqual(view["counts"], {"kept": 12})
        self.assertEqual(
            view["artifacts"][0]["download_url"],
            f"/api/v1/runs/{self.run_id}/artifacts/digest.html",
        )

    def test_view_survives_unparseable_metadata(self) -> None:
        (self.work_dir / "run_metadata.json").write_text("{not json", encoding="utf-8")

        view = self.service.view(self.service.get(self.run_id))

        self.assertEqual(view["email_status"], "")
        self.assertEqual(view["completed_steps"], [])


if __name__ == "__main__":
    unittest.main()
