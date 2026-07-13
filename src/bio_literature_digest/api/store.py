from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


STATUS_FILENAME = "status.json"
ACTIVE_LOCK_FILENAME = ".active-run.lock"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ActiveRunError(RuntimeError):
    pass


class RunStore:
    """Persist API run state and enforce one active producer process."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()

    @property
    def active_lock_path(self) -> Path:
        return self.root / ACTIVE_LOCK_FILENAME

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid4().hex
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, mode=0o700)
        record: dict[str, Any] = {
            "id": run_id,
            "status": "queued",
            "created_at_utc": utc_now(),
            "started_at_utc": "",
            "finished_at_utc": "",
            "exit_code": None,
            "current_step": "",
            "failure_message": "",
            "request": request,
            "work_dir": str(run_dir / "work"),
            "log_file": str(run_dir / "run.log"),
        }
        self.write(record)
        return record

    def acquire_active_slot(self, run_id: str) -> None:
        payload = json.dumps({"run_id": run_id, "acquired_at_utc": utc_now()})
        try:
            fd = os.open(str(self.active_lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            active_id = self.active_run_id()
            raise ActiveRunError(f"another digest run is active: {active_id or 'unknown'}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)

    def release_active_slot(self, run_id: str) -> None:
        with self._lock:
            if self.active_run_id() == run_id:
                self.active_lock_path.unlink(missing_ok=True)

    def active_run_id(self) -> str:
        try:
            payload = json.loads(self.active_lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return ""
        return str(payload.get("run_id", ""))

    def recover_interrupted_run(self) -> None:
        run_id = self.active_run_id()
        if not run_id:
            return
        try:
            record = self.get(run_id)
        except KeyError:
            self.active_lock_path.unlink(missing_ok=True)
            return
        if record.get("status") in {"queued", "running"}:
            self.update(
                run_id,
                status="interrupted",
                finished_at_utc=utc_now(),
                failure_message="API service restarted while the digest run was active",
            )
        self.active_lock_path.unlink(missing_ok=True)

    def get(self, run_id: str) -> dict[str, Any]:
        path = self._status_path(run_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(run_id) from exc
        if not isinstance(payload, dict):
            raise KeyError(run_id)
        return payload

    def write(self, record: dict[str, Any]) -> None:
        path = self._status_path(str(record["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
            path.chmod(0o600)

    def update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            record = self.get(run_id)
            record.update(changes)
            self.write(record)
            return record

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self.root.glob(f"*/{STATUS_FILENAME}"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(payload, dict):
                records.append(payload)
        records.sort(key=lambda item: str(item.get("created_at_utc", "")), reverse=True)
        return records[:limit]

    def run_dir(self, run_id: str) -> Path:
        self.get(run_id)
        return self.root / run_id

    def _status_path(self, run_id: str) -> Path:
        if not run_id or any(character not in "0123456789abcdef" for character in run_id):
            raise KeyError(run_id)
        return self.root / run_id / STATUS_FILENAME
