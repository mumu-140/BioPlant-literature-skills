"""Shared test helpers — import from here to avoid copy-paste across test files.

Usage:
    from helpers import SKILL_DIR, SCRIPTS_DIR, load_script_module, FakeResponse, write_jsonl
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


# ---------------------------------------------------------------------------
# Common paths
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
SRC_DIR = SKILL_DIR / "src"

# Ensure scripts/ and src/ are importable
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------------------------------------------------------------------
# Script module loader (replaces 4 identical load_module() implementations)
# ---------------------------------------------------------------------------

def load_script_module(script_name: str, module_alias: str | None = None) -> ModuleType:
    """Load a script from scripts/ as a module, handling sys.path setup.

    Args:
        script_name: Filename in scripts/ (e.g. "filter_bio_relevance.py")
        module_alias: Optional module name for importlib (defaults to script_name sans .py)

    Returns:
        The loaded module object.
    """
    script_path = SCRIPTS_DIR / script_name
    if module_alias is None:
        module_alias = script_name.replace(".py", "_module")
    scripts_dir = str(script_path.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(module_alias, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {script_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fake HTTP response (replaces 2 identical FakeResponse classes)
# ---------------------------------------------------------------------------

class FakeResponse:
    """Mock urllib response for testing HTTP-based providers."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# JSONL helpers (replaces inline json.dumps loops in 10+ test files)
# ---------------------------------------------------------------------------

def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write records as newline-delimited JSON."""
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict]:
    """Read newline-delimited JSON file."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
