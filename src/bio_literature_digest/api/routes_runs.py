from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from .dependencies import require_roles
from .models import ArtifactInfo, RunAccepted, RunRequest, RunStatus
from .runner import DigestRunManager
from .store import ActiveRunError, RunStore


ARTIFACT_NAMES = {
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

router = APIRouter(prefix="/api/v1")
read_access = Depends(require_roles("admin", "operator", "viewer"))
run_access = Depends(require_roles("admin", "operator"))


def run_manager(request: Request) -> DigestRunManager:
    return request.app.state.run_manager


@router.post("/runs", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED, dependencies=[run_access], tags=["runs"])
async def create_run(payload: RunRequest, request: Request) -> RunAccepted:
    manager = run_manager(request)
    try:
        record = manager.submit(payload)
    except ActiveRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run_id = str(record["id"])
    return RunAccepted(id=run_id, status=str(record["status"]), status_url=f"/api/v1/runs/{run_id}")


@router.get("/runs", response_model=list[RunStatus], dependencies=[read_access], tags=["runs"])
async def list_runs(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[RunStatus]:
    manager = run_manager(request)
    return [serialize_run(record) for record in manager.store.list_recent(limit)]


@router.get("/runs/{run_id}", response_model=RunStatus, dependencies=[read_access], tags=["runs"])
async def get_run(run_id: str, request: Request) -> RunStatus:
    return serialize_run(get_record(run_manager(request).store, run_id))


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactInfo], dependencies=[read_access], tags=["artifacts"])
async def list_artifacts(run_id: str, request: Request) -> list[ArtifactInfo]:
    store = run_manager(request).store
    get_record(store, run_id)
    return collect_artifacts(store, run_id)


@router.get("/runs/{run_id}/artifacts/{artifact_name}", dependencies=[read_access], tags=["artifacts"])
async def download_artifact(run_id: str, artifact_name: str, request: Request) -> FileResponse:
    if artifact_name not in ARTIFACT_NAMES:
        raise HTTPException(status_code=404, detail="artifact not found")
    run_dir = run_manager(request).store.run_dir(run_id)
    path = run_dir / "run.log" if artifact_name == "run.log" else run_dir / "work" / artifact_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, filename=artifact_name)


def get_record(store: RunStore, run_id: str) -> dict[str, Any]:
    try:
        return store.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


def collect_artifacts(store: RunStore, run_id: str) -> list[ArtifactInfo]:
    run_dir = store.run_dir(run_id)
    artifacts: list[ArtifactInfo] = []
    for name in sorted(ARTIFACT_NAMES):
        path = run_dir / "run.log" if name == "run.log" else run_dir / "work" / name
        if path.is_file():
            artifacts.append(
                ArtifactInfo(name=name, size=path.stat().st_size, download_url=f"/api/v1/runs/{run_id}/artifacts/{name}")
            )
    return artifacts


def serialize_run(record: dict[str, Any]) -> RunStatus:
    store = RunStore(Path(str(record["work_dir"])).parent.parent)
    return RunStatus(
        id=str(record["id"]),
        status=str(record["status"]),
        created_at_utc=str(record.get("created_at_utc", "")),
        started_at_utc=str(record.get("started_at_utc", "")),
        finished_at_utc=str(record.get("finished_at_utc", "")),
        exit_code=record.get("exit_code"),
        current_step=str(record.get("current_step", "")),
        failure_message=str(record.get("failure_message", "")),
        artifacts=collect_artifacts(store, str(record["id"])),
    )
