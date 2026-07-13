from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from .auth import AuthStore
from .configuration import ConfigManager
from .routes_config import router as config_router
from .routes_runs import router as runs_router
from .routes_users import router as users_router
from .runner import DigestRunManager
from .store import RunStore


def create_app(
    *,
    api_key: str | None = None,
    run_root: Path | None = None,
    skill_dir: Path | None = None,
    runtime_config: Path | None = None,
    manager: DigestRunManager | None = None,
    auth_store: AuthStore | None = None,
    config_manager: ConfigManager | None = None,
) -> FastAPI:
    """Create the remote API with project-local runtime and identity stores."""
    resolved_skill_dir = (skill_dir or Path(__file__).resolve().parents[3]).resolve()
    resolved_key = api_key if api_key is not None else os.environ.get("BIO_DIGEST_API_KEY", "")
    resolved_root = run_root or Path(
        os.environ.get("BIO_DIGEST_API_RUN_ROOT", str(resolved_skill_dir / "var" / "api" / "runs"))
    )
    resolved_runtime = runtime_config or Path(
        os.environ.get(
            "BIO_DIGEST_RUNTIME_CONFIG",
            str(resolved_skill_dir / "local" / "runtime" / "production.yaml"),
        )
    )

    app = FastAPI(
        title="Bio Literature Digest API",
        version="1.0.0",
        description="Remote API for launching and downloading biology literature digest runs.",
    )
    app.state.bootstrap_key = resolved_key
    app.state.run_manager = manager or DigestRunManager(
        RunStore(resolved_root),
        resolved_skill_dir,
        resolved_runtime,
    )
    app.state.auth_store = auth_store or AuthStore(resolved_root.parent / "auth.sqlite3", resolved_key)
    app.state.config_manager = config_manager or ConfigManager(
        resolved_skill_dir / "config" / "content" / "journal_watchlist.yaml",
        resolved_skill_dir / "config" / "content" / "category_rules.yaml",
        resolved_skill_dir / "local" / "integrations" / "users.yaml",
        resolved_skill_dir / "var" / "api" / "config-backups",
    )

    @app.get("/healthz", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(runs_router)
    app.include_router(users_router)
    app.include_router(config_router)
    return app
