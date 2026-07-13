from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .store import utc_now


ROLES = {"admin", "operator", "viewer"}


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    role: str


class AuthStore:
    """SQLite-backed API identities with hashed opaque access tokens."""

    def __init__(self, path: Path, bootstrap_token: str = "") -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if bootstrap_token:
            self._bootstrap_admin(bootstrap_token)

    def authenticate(self, token: str) -> Principal | None:
        token_hash = self._hash_token(token)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, role FROM api_users WHERE token_hash = ? AND is_active = 1",
                (token_hash,),
            ).fetchone()
        return Principal(*row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, username, display_name, role, token_prefix, is_active, created_at_utc, updated_at_utc "
                "FROM api_users ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_user(self, username: str, display_name: str, role: str, actor: Principal) -> tuple[dict[str, Any], str]:
        self._validate_role(role)
        token = self._new_token()
        now = utc_now()
        user_id = uuid4().hex
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO api_users VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (user_id, username, display_name, role, self._hash_token(token), token[:12], now, now),
                )
                self._write_audit(connection, actor, "user.create", user_id, {"username": username, "role": role})
        except sqlite3.IntegrityError as exc:
            raise ValueError("username already exists") from exc
        return self.get_user(user_id), token

    def get_user(self, user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, display_name, role, token_prefix, is_active, created_at_utc, updated_at_utc "
                "FROM api_users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            raise KeyError(user_id)
        return dict(row)

    def update_user(self, user_id: str, role: str | None, is_active: bool | None, actor: Principal) -> dict[str, Any]:
        user = self.get_user(user_id)
        new_role = role or str(user["role"])
        self._validate_role(new_role)
        new_active = bool(user["is_active"]) if is_active is None else is_active
        if user_id == actor.id and (not new_active or new_role != "admin"):
            raise ValueError("administrators cannot deactivate or demote themselves")
        if user["role"] == "admin" and (new_role != "admin" or not new_active):
            self._require_other_admin(user_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE api_users SET role = ?, is_active = ?, updated_at_utc = ? WHERE id = ?",
                (new_role, int(new_active), utc_now(), user_id),
            )
            self._write_audit(connection, actor, "user.update", user_id, {"role": new_role, "is_active": new_active})
        return self.get_user(user_id)

    def delete_user(self, user_id: str, actor: Principal) -> None:
        user = self.get_user(user_id)
        if user_id == actor.id:
            raise ValueError("administrators cannot delete themselves")
        if user["role"] == "admin":
            self._require_other_admin(user_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM api_users WHERE id = ?", (user_id,))
            self._write_audit(connection, actor, "user.delete", user_id, {"username": user["username"]})

    def rotate_token(self, user_id: str, actor: Principal) -> str:
        self.get_user(user_id)
        token = self._new_token()
        with self._connect() as connection:
            connection.execute(
                "UPDATE api_users SET token_hash = ?, token_prefix = ?, updated_at_utc = ? WHERE id = ?",
                (self._hash_token(token), token[:12], utc_now(), user_id),
            )
            self._write_audit(connection, actor, "user.token.rotate", user_id, {})
        return token

    def audit(self, actor: Principal, action: str, target: str, details: dict[str, Any]) -> None:
        with self._connect() as connection:
            self._write_audit(connection, actor, action, target, details)

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, created_at_utc, actor_id, actor_username, action, target, details_json "
                "FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
                    role TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, token_prefix TEXT NOT NULL,
                    is_active INTEGER NOT NULL, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at_utc TEXT NOT NULL,
                    actor_id TEXT NOT NULL, actor_username TEXT NOT NULL, action TEXT NOT NULL,
                    target TEXT NOT NULL, details_json TEXT NOT NULL
                );
                """
            )
        self.path.chmod(0o600)

    def _bootstrap_admin(self, token: str) -> None:
        with self._connect() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM api_users").fetchone()[0])
            if count:
                return
            now = utc_now()
            connection.execute(
                "INSERT INTO api_users VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (uuid4().hex, "bootstrap-admin", "Bootstrap Administrator", "admin", self._hash_token(token), token[:12], now, now),
            )

    def _require_other_admin(self, excluded_id: str) -> None:
        with self._connect() as connection:
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM api_users WHERE role = 'admin' AND is_active = 1 AND id != ?",
                    (excluded_id,),
                ).fetchone()[0]
            )
        if count == 0:
            raise ValueError("the last active administrator cannot be removed")

    @staticmethod
    def _write_audit(
        connection: sqlite3.Connection,
        actor: Principal,
        action: str,
        target: str,
        details: dict[str, Any],
    ) -> None:
        import json

        connection.execute(
            "INSERT INTO audit_log (created_at_utc, actor_id, actor_username, action, target, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (utc_now(), actor.id, actor.username, action, target, json.dumps(details, ensure_ascii=False)),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _new_token() -> str:
        return f"bdg_{secrets.token_urlsafe(36)}"

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(ROLES))}")
