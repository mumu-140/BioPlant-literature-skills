from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

import yaml

from bio_literature_digest.fetching.http import validate_public_http_url

from .store import utc_now


class ConfigManager:
    """Validate and atomically update API-managed YAML configuration."""

    def __init__(self, watchlist: Path, rules: Path, recipients: Path, backup_root: Path) -> None:
        self.paths = {"journals": watchlist, "category-rules": rules, "recipients": recipients}
        self.backup_root = backup_root
        self._lock = threading.RLock()

    def read(self, name: str) -> dict[str, Any]:
        path = self.paths[name]
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"{name} config must be an object")
        return payload

    def replace(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate(name, payload)
        path = self.paths[name]
        with self._lock:
            self._backup(name, path)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
            temporary.replace(path)
        return self.read(name)

    def upsert_journal(self, journal_id: str, journal: dict[str, Any], create_only: bool = False) -> dict[str, Any]:
        if journal.get("id") != journal_id:
            raise ValueError("journal body id must match path id")
        with self._lock:
            payload = self.read("journals")
            journals = list(payload.get("journals", []))
            index = next((i for i, item in enumerate(journals) if item.get("id") == journal_id), None)
            if create_only and index is not None:
                raise ValueError("journal already exists")
            if index is None:
                journals.append(journal)
            else:
                journals[index] = journal
            payload["journals"] = journals
            self.replace("journals", payload)
        return journal

    def delete_journal(self, journal_id: str) -> None:
        with self._lock:
            payload = self.read("journals")
            journals = list(payload.get("journals", []))
            filtered = [item for item in journals if item.get("id") != journal_id]
            if len(filtered) == len(journals):
                raise KeyError(journal_id)
            payload["journals"] = filtered
            self.replace("journals", payload)

    def _backup(self, name: str, path: Path) -> None:
        if not path.exists():
            return
        stamp = utc_now().replace(":", "").replace("-", "")
        target_dir = self.backup_root / name
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_path = target_dir / f"{stamp}-{path.name}"
        shutil.copy2(path, backup_path)
        backup_path.chmod(0o600)

    @staticmethod
    def _validate(name: str, payload: dict[str, Any]) -> None:
        if name == "journals":
            items = payload.get("journals")
            if not isinstance(items, list):
                raise ValueError("journals must be a list")
            ids = [str(item.get("id", "")) for item in items if isinstance(item, dict)]
            if len(ids) != len(items) or any(not value for value in ids) or len(ids) != len(set(ids)):
                raise ValueError("every journal must have a unique non-empty id")
            for item in items:
                ConfigManager._validate_source_locators(item.get("source_locator"))
        elif name == "category-rules":
            categories = payload.get("categories")
            if not isinstance(categories, list):
                raise ValueError("categories must be a list")
            ids = [str(item.get("id", "")) for item in categories if isinstance(item, dict)]
            if len(ids) != len(categories) or any(not value for value in ids):
                raise ValueError("every category must have a non-empty id")
            if "other" not in ids or len(ids) != len(set(ids)):
                raise ValueError("category ids must be unique and include other")
        elif name == "recipients":
            users = payload.get("users")
            if not isinstance(users, list):
                raise ValueError("users must be a list")
            emails = [str(item.get("email", "")).lower() for item in users if isinstance(item, dict)]
            if len(emails) != len(users) or any("@" not in email for email in emails) or len(emails) != len(set(emails)):
                raise ValueError("every recipient must have a unique valid email")

    @staticmethod
    def _validate_source_locators(value: Any) -> None:
        if value is None or value == "":
            return
        locators = value if isinstance(value, list) else [value]
        if not locators or any(not isinstance(locator, str) or not locator.strip() for locator in locators):
            raise ValueError("source_locator must be a URL or a non-empty URL list")
        for locator in locators:
            validate_public_http_url(locator, resolve_host=False)
