from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .auth import AuthStore, Principal
from .dependencies import current_principal, require_roles
from .models import TokenRotated, UserCreate, UserCreated, UserUpdate, UserView


router = APIRouter(prefix="/api/v1")
admin_access = Depends(require_roles("admin"))


def identities(request: Request) -> AuthStore:
    return request.app.state.auth_store


@router.get("/me", tags=["users"])
async def me(principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, str]:
    return {"id": principal.id, "username": principal.username, "role": principal.role}


@router.get("/users", response_model=list[UserView], dependencies=[admin_access], tags=["users"])
async def list_users(request: Request) -> list[dict[str, Any]]:
    return identities(request).list_users()


@router.post("/users", response_model=UserCreated, status_code=201, tags=["users"])
async def create_user(
    payload: UserCreate,
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> dict[str, Any]:
    try:
        user, token = identities(request).create_user(payload.username, payload.display_name, payload.role, actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**user, "token": token}


@router.patch("/users/{user_id}", response_model=UserView, tags=["users"])
async def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> dict[str, Any]:
    try:
        return identities(request).update_user(user_id, payload.role, payload.is_active, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/users/{user_id}", status_code=204, tags=["users"])
async def delete_user(
    user_id: str,
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> None:
    try:
        identities(request).delete_user(user_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/users/{user_id}/rotate-token", response_model=TokenRotated, tags=["users"])
async def rotate_user_token(
    user_id: str,
    request: Request,
    actor: Annotated[Principal, Depends(require_roles("admin"))],
) -> TokenRotated:
    try:
        token = identities(request).rotate_token(user_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    return TokenRotated(user_id=user_id, token=token)


@router.get("/audit-log", dependencies=[admin_access], tags=["audit"])
async def audit_log(request: Request, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[dict[str, Any]]:
    return identities(request).list_audit(limit)
