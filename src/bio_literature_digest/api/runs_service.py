"""Framework-free run inspection shared by the HTTP API and the MCP server.

Everything here is stdlib-only on purpose. The FastAPI routers in
:mod:`bio_literature_digest.api.routes_runs` and the stdio MCP server in
:mod:`bio_literature_digest.mcp.server` both call this module, so the two
surfaces cannot drift apart, and the MCP server stays runnable on hosts where
the web stack is not installed.

The artifact allow-list lives here rather than in the router: it is the
containment boundary that keeps either surface from reading arbitrary paths
out of a run directory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..masking import mask_email_text
from .store import RunStore

# Files a client may read out of a run directory. ``status.json`` is absent on
# purpose: it is the store's own bookkeeping, not a run artifact.
ARTIFACT_NAMES: frozenset[str] = frozenset(
    {
        "digest.html",
        "digest.csv",
        "digest.xlsx",
        "review_queue.html",
        "review_queue.csv",
        "review_queue.xlsx",
        "daily_review.html",
        "daily_review.csv",
        "daily_review.xlsx",
        "run_metadata.json",
        "rule_feedback_report.md",
        "classification_suggestions.md",
        "classification_suggestions.json",
        "glossary_candidates.md",
        "run.log",
    }
)

# Artifacts that are safe to inline as text. The spreadsheet exports are
# binary and must be fetched over HTTP instead.
TEXT_ARTIFACT_SUFFIXES: frozenset[str] = frozenset({".csv", ".html", ".json", ".log", ".md"})

METADATA_FILENAME = "run_metadata.json"
LOG_FILENAME = "run.log"

# The producer's final pipeline step. A failure there means every artifact was
# already written, so the run is reported as ``partial_success`` instead of
# being flattened into ``failed``.
DELIVERY_STEP = "send_email"

RUN_STATUSES: frozenset[str] = frozenset(
    {"queued", "running", "success", "partial_success", "failed", "interrupted"}
)


class ArtifactNotFoundError(LookupError):
    """Raised when an artifact is not allow-listed or not present on disk."""


def load_run_metadata(path: Path) -> dict[str, Any]:
    """Read ``run_metadata.json``, treating any unusable file as absent."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _text(value: Any) -> str:
    """Render a metadata scalar as a string, mapping ``None`` to empty."""
    return "" if value is None else str(value)


def summarize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Project the run-metadata contract onto the fields clients need.

    ``run_metadata.json`` is rewritten after every pipeline step, so these
    fields expose progress while a run is still going, not just at the end.
    ``email_status`` is propagated verbatim -- ``scripts/run_digest.py`` owns
    that derivation and this layer must never recompute it.
    """
    raw_steps = metadata.get("completed_steps")
    completed_steps = [str(step) for step in raw_steps] if isinstance(raw_steps, list) else []

    raw_counts = metadata.get("counts")
    counts: dict[str, int] = {}
    if isinstance(raw_counts, dict):
        for key, value in raw_counts.items():
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            counts[str(key)] = value

    return {
        "email_status": _text(metadata.get("email_status")),
        "failed_step": _text(metadata.get("failed_step")),
        "failure_type": _text(metadata.get("failure_type")),
        "completed_steps": completed_steps,
        "counts": counts,
    }


def resolve_outcome(*, exit_code: int, metadata: dict[str, Any]) -> tuple[str, str]:
    """Derive ``(status, failure_message)`` for a finished producer process.

    Replaces the old ``returncode == 0 and metadata["status"] == "success"``
    test, which collapsed four distinct outcomes into a bare ``failed`` with an
    empty message -- including the case where metadata was missing entirely.
    """
    if not metadata:
        if exit_code == 0:
            return "failed", f"producer exited 0 without writing {METADATA_FILENAME}"
        return "failed", f"producer exited with code {exit_code} without writing {METADATA_FILENAME}"

    reported = _text(metadata.get("status"))
    failure_message = _text(metadata.get("failure_message"))
    failed_step = _text(metadata.get("failed_step"))

    if reported == "success":
        if exit_code == 0:
            return "success", ""
        return "failed", (
            failure_message
            or f"{METADATA_FILENAME} reported success but the producer exited with code {exit_code}"
        )

    if failed_step == DELIVERY_STEP:
        return "partial_success", (
            failure_message or "email delivery failed after every artifact was produced"
        )

    return "failed", (
        failure_message or f"producer failed at step {failed_step or 'unknown'}"
    )


class RunsService:
    """Read-only projection of the run store, shared by every client surface."""

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def get(self, run_id: str) -> dict[str, Any]:
        """Return a raw store record. Raises ``KeyError`` when unknown."""
        return self.store.get(run_id)

    def list_recent(self, limit: int) -> list[dict[str, Any]]:
        return self.store.list_recent(limit)

    def metadata(self, run_id: str) -> dict[str, Any]:
        return load_run_metadata(self.store.run_dir(run_id) / "work" / METADATA_FILENAME)

    def artifact_path(self, run_id: str, name: str) -> Path:
        """Resolve an allow-listed artifact to a path that exists on disk."""
        if name not in ARTIFACT_NAMES:
            raise ArtifactNotFoundError(name)
        run_dir = self.store.run_dir(run_id)
        path = run_dir / LOG_FILENAME if name == LOG_FILENAME else run_dir / "work" / name
        if not path.is_file():
            raise ArtifactNotFoundError(name)
        return path

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """List the artifacts present for a run, in stable name order."""
        entries: list[dict[str, Any]] = []
        for name in sorted(ARTIFACT_NAMES):
            try:
                path = self.artifact_path(run_id, name)
            except ArtifactNotFoundError:
                continue
            entries.append(
                {
                    "name": name,
                    "size": path.stat().st_size,
                    "download_url": f"/api/v1/runs/{run_id}/artifacts/{name}",
                }
            )
        return entries

    def read_text_artifact(self, run_id: str, name: str, max_bytes: int) -> dict[str, Any]:
        """Read a text artifact, capped and address-masked, for local clients."""
        path = self.artifact_path(run_id, name)
        if path.suffix.lower() not in TEXT_ARTIFACT_SUFFIXES:
            raise ArtifactNotFoundError(f"{name} is not a text artifact")
        limit = max(1, int(max_bytes))
        size = path.stat().st_size
        with path.open("rb") as handle:
            raw = handle.read(limit)
        return {
            "name": name,
            "size": size,
            "truncated": size > len(raw),
            "text": mask_email_text(raw.decode("utf-8", errors="replace")),
        }

    def view(self, record: dict[str, Any]) -> dict[str, Any]:
        """Render one store record plus its live metadata and artifacts."""
        run_id = str(record["id"])
        view: dict[str, Any] = {
            "id": run_id,
            "status": _text(record.get("status")),
            "created_at_utc": _text(record.get("created_at_utc")),
            "started_at_utc": _text(record.get("started_at_utc")),
            "finished_at_utc": _text(record.get("finished_at_utc")),
            "exit_code": record.get("exit_code"),
            "current_step": _text(record.get("current_step")),
            # Delivery failures quote the recipient list, so this is masked on the
            # way out rather than at write time -- the run log keeps the raw text
            # for operators who can already read the run directory.
            "failure_message": mask_email_text(_text(record.get("failure_message"))),
        }
        view.update(summarize_metadata(self.metadata(run_id)))
        view["artifacts"] = self.artifacts(run_id)
        return view

    def views(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.view(record) for record in records]
