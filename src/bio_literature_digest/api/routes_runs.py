from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from .dependencies import require_roles
from .models import ArtifactInfo, RunAccepted, RunRequest, RunStatus
from .runner import DigestRunManager
from .runs_service import ArtifactNotFoundError, RunsService
from .store import ActiveRunError

router = APIRouter(prefix="/api/v1")
read_access = Depends(require_roles("admin", "operator", "viewer"))
run_access = Depends(require_roles("admin", "operator"))


def run_manager(request: Request) -> DigestRunManager:
    return request.app.state.run_manager


def runs_service(request: Request) -> RunsService:
    """Wrap the manager's store in the shared read-only projection.

    The projection logic lives in :mod:`.runs_service` so the MCP server serves
    byte-identical run views without importing FastAPI.
    """
    return RunsService(run_manager(request).store)


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
    service = runs_service(request)
    return [RunStatus(**view) for view in service.views(service.list_recent(limit))]


@router.get("/runs/{run_id}", response_model=RunStatus, dependencies=[read_access], tags=["runs"])
async def get_run(run_id: str, request: Request) -> RunStatus:
    service = runs_service(request)
    return RunStatus(**service.view(get_record(service, run_id)))


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactInfo], dependencies=[read_access], tags=["artifacts"])
async def list_artifacts(run_id: str, request: Request) -> list[ArtifactInfo]:
    service = runs_service(request)
    get_record(service, run_id)
    return [ArtifactInfo(**entry) for entry in service.artifacts(run_id)]


@router.get("/runs/{run_id}/artifacts/{artifact_name}", dependencies=[read_access], tags=["artifacts"])
async def download_artifact(run_id: str, artifact_name: str, request: Request) -> FileResponse:
    try:
        path = runs_service(request).artifact_path(run_id, artifact_name)
    except (ArtifactNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    return FileResponse(path, filename=artifact_name)


def get_record(service: RunsService, run_id: str) -> dict[str, object]:
    try:
        return service.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
