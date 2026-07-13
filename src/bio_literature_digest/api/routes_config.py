from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import AuthStore, Principal
from .configuration import ConfigManager
from .dependencies import require_roles


router = APIRouter(prefix="/api/v1/config")
read_access = Depends(require_roles("admin", "operator", "viewer"))
admin_access = Depends(require_roles("admin"))


def configs(request: Request) -> ConfigManager:
    return request.app.state.config_manager


def identities(request: Request) -> AuthStore:
    return request.app.state.auth_store


def ensure_no_active_run(request: Request) -> None:
    active_run_id = request.app.state.run_manager.store.active_run_id()
    if active_run_id:
        raise HTTPException(
            status_code=409,
            detail=f"configuration cannot be changed while run {active_run_id} is active",
        )


@router.get("/journals", dependencies=[read_access], tags=["configuration"])
async def get_journals(request: Request) -> dict[str, Any]:
    return configs(request).read("journals")


@router.post("/journals", status_code=201, tags=["configuration"])
async def create_journal(
    journal: dict[str, Any],
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> dict[str, Any]:
    ensure_no_active_run(request)
    journal_id = str(journal.get("id", ""))
    try:
        result = configs(request).upsert_journal(journal_id, journal, create_only=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    identities(request).audit(actor, "config.journal.create", journal_id, {})
    return result


@router.put("/journals/{journal_id}", tags=["configuration"])
async def update_journal(
    journal_id: str,
    journal: dict[str, Any],
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> dict[str, Any]:
    ensure_no_active_run(request)
    try:
        result = configs(request).upsert_journal(journal_id, journal)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    identities(request).audit(actor, "config.journal.update", journal_id, {})
    return result


@router.delete("/journals/{journal_id}", status_code=204, tags=["configuration"])
async def delete_journal(
    journal_id: str,
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> None:
    ensure_no_active_run(request)
    try:
        configs(request).delete_journal(journal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journal not found") from exc
    identities(request).audit(actor, "config.journal.delete", journal_id, {})


@router.get("/category-rules", dependencies=[read_access], tags=["configuration"])
async def get_category_rules(request: Request) -> dict[str, Any]:
    return configs(request).read("category-rules")


@router.put("/category-rules", tags=["configuration"])
async def replace_category_rules(
    payload: dict[str, Any],
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> dict[str, Any]:
    ensure_no_active_run(request)
    try:
        result = configs(request).replace("category-rules", payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    identities(request).audit(actor, "config.category-rules.replace", "category-rules", {})
    return result


@router.get("/recipients", dependencies=[admin_access], tags=["configuration"])
async def get_recipients(request: Request) -> dict[str, Any]:
    return configs(request).read("recipients")


@router.put("/recipients", tags=["configuration"])
async def replace_recipients(
    payload: dict[str, Any],
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> dict[str, Any]:
    ensure_no_active_run(request)
    try:
        result = configs(request).replace("recipients", payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    identities(request).audit(actor, "config.recipients.replace", "recipients", {"count": len(payload.get("users", []))})
    return result
