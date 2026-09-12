from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

import yaml

from bio_literature_digest.fetching.http import validate_public_http_url

from .store import utc_now


class _IndentedSafeDumper(yaml.SafeDumper):
    """Match the repository's indented block-sequence style."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def _dump_yaml(payload: Any) -> str:
    return yaml.dump(
        payload,
        Dumper=_IndentedSafeDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    )


def _dump_journal(journal: dict[str, Any]) -> list[str]:
    rendered = _dump_yaml([journal])
    return [f"  {line}" if line.strip() else line for line in rendered.splitlines(keepends=True)]


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

    def _write(self, name: str, payload: dict[str, Any], path: Path) -> None:
        if name == "journals":
            current_text = path.read_text(encoding="utf-8") if path.exists() else "journals:\n"
            current_payload = yaml.safe_load(current_text) or {}
            current_journals = current_payload.get("journals", [])
            updated_journals = payload.get("journals", [])
            if current_payload == payload:
                text = current_text
            elif isinstance(current_journals, list) and isinstance(updated_journals, list):
                text = self._update_journals(current_text, current_journals, updated_journals)
            else:
                text = _dump_yaml(payload)
        else:
            text = _dump_yaml(payload)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _update_journals(
        text: str,
        current: list[dict[str, Any]],
        updated: list[dict[str, Any]],
    ) -> str:
        lines = text.splitlines(keepends=True)
        starts = [i for i, line in enumerate(lines) if line.startswith("  - id:")]
        if len(starts) != len(current):
            return _dump_yaml({"journals": updated})
        end = next((i for i, line in enumerate(lines[starts[-1] + 1 :], starts[-1] + 1) if line and not line.startswith(" ")), len(lines)) if starts else len(lines)
        suffix = lines[end:]
        while suffix and not suffix[0].strip():
            suffix.pop(0)
        blocks: dict[str, list[str]] = {}
        for index, journal in enumerate(current):
            journal_id = journal.get("id")
            if not isinstance(journal_id, str):
                return _dump_yaml({"journals": updated})
            block_end = starts[index + 1] if index + 1 < len(starts) else end
            blocks[journal_id] = lines[starts[index]:block_end]
            if index + 1 == len(starts):
                while blocks[journal_id] and not blocks[journal_id][-1].strip():
                    blocks[journal_id].pop()
        body: list[str] = []
        kept_original_blocks = True
        current_by_id = {item.get("id"): item for item in current if isinstance(item, dict)}
        for journal in updated:
            journal_id = journal.get("id")
            if journal_id in blocks and current_by_id.get(journal_id) == journal:
                block = blocks[journal_id]
            else:
                kept_original_blocks = False
                block = _dump_journal(journal)
                if body:
                    block.insert(0, "\n")
            body.extend(block)
        separator = [] if kept_original_blocks else (["\n"] if body and suffix else [])
        return "".join(lines[: starts[0]] + body + separator + suffix) if starts else _dump_yaml({"journals": updated})

    def replace(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate(name, payload)
        path = self.paths[name]
        with self._lock:
            current = self.read(name)
            self._backup(name, path)
            if current == payload:
                return current
            self._write(name, payload, path)
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
