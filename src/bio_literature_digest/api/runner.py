from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .models import RunRequest
from .store import RunStore, utc_now


class DigestRunManager:
    """Execute the existing production CLI behind a persistent run registry."""

    def __init__(self, store: RunStore, skill_dir: Path, runtime_config: Path) -> None:
        self.store = store
        self.skill_dir = skill_dir.resolve()
        self.runtime_config = runtime_config.resolve()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bio-digest-api")
        self.store.recover_interrupted_run()

    def submit(self, request: RunRequest) -> dict[str, Any]:
        record = self.store.create(request.model_dump(mode="json"))
        try:
            self.store.acquire_active_slot(str(record["id"]))
        except Exception:
            self.store.update(
                str(record["id"]),
                status="failed",
                finished_at_utc=utc_now(),
                failure_message="another digest run is already active",
            )
            raise
        self.executor.submit(self._execute, str(record["id"]), request)
        return record

    def _execute(self, run_id: str, request: RunRequest) -> None:
        record = self.store.get(run_id)
        work_dir = Path(str(record["work_dir"]))
        log_path = Path(str(record["log_file"]))
        work_dir.mkdir(parents=True, exist_ok=True)
        command = self.build_command(work_dir, request)
        self.store.update(run_id, status="running", started_at_utc=utc_now())

        try:
            with log_path.open("w", encoding="utf-8") as log_handle:
                log_path.chmod(0o600)
                completed = subprocess.run(
                    command,
                    cwd=self.skill_dir,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            metadata = self._load_metadata(work_dir / "run_metadata.json")
            succeeded = completed.returncode == 0 and metadata.get("status") == "success"
            self.store.update(
                run_id,
                status="success" if succeeded else "failed",
                finished_at_utc=utc_now(),
                exit_code=completed.returncode,
                current_step=str(metadata.get("current_step", "")),
                failure_message=str(metadata.get("failure_message", "")),
            )
        except Exception as exc:  # noqa: BLE001 - persist all runner failures for remote clients.
            self.store.update(
                run_id,
                status="failed",
                finished_at_utc=utc_now(),
                failure_message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self.store.release_active_slot(run_id)

    def build_command(self, work_dir: Path, request: RunRequest) -> list[str]:
        command = [
            sys.executable,
            str(self.skill_dir / "scripts" / "run_production_digest.py"),
            "--runtime-config",
            str(self.runtime_config),
            "--work-dir",
            str(work_dir),
        ]
        if request.skip_email:
            command.append("--skip-email")
        command.append("--allow-review-pending" if request.allow_review_pending else "--no-allow-review-pending")
        if request.summary_provider:
            command.extend(["--summary-provider", request.summary_provider])
        if request.review_provider:
            command.extend(["--review-provider", request.review_provider])
        if request.window_start and request.window_end:
            command.extend(
                [
                    "--window-start",
                    request.window_start.isoformat().replace("+00:00", "Z"),
                    "--window-end",
                    request.window_end.isoformat().replace("+00:00", "Z"),
                ]
            )
        return command

    @staticmethod
    def _load_metadata(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
