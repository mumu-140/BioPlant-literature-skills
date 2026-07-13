from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import AuthStore, Principal


bearer_scheme = HTTPBearer(auto_error=False)


def auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    identities = auth_store(request)
    if not request.app.state.bootstrap_key and not identities.list_users():
        raise HTTPException(status_code=503, detail="BIO_DIGEST_API_KEY is not configured")
    supplied_key = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else x_api_key
    principal = identities.authenticate(supplied_key or "")
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    return principal


def require_roles(*roles: str) -> Callable[..., Principal]:
    """Build a FastAPI dependency that limits access to the supplied roles."""

    async def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient permissions")
        return principal

    return dependency
