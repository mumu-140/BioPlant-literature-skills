#!/usr/bin/env python3
"""Unified bootstrap for all scripts/*.py — import this first.

Responsibilities:
  1. Compute SCRIPT_DIR / SKILL_DIR / SRC_DIR from filesystem.
  2. Ensure ``src/`` is on sys.path so ``bio_literature_digest.*`` is importable.
  3. Re-export everything from ``project_layout`` (paths, config helpers).

Usage in any sibling script::

    try:
        from scripts._bootstrap import SKILL_DIR, canonical_paths, load_runtime_config
    except ModuleNotFoundError:
        from _bootstrap import SKILL_DIR, canonical_paths, load_runtime_config
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SRC_DIR = SKILL_DIR / "src"

# Make src/ importable (idempotent).
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Make scripts/ importable (idempotent) — so ``from common import ...`` works
# regardless of cwd.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Re-export everything from project_layout so callers can do:
#   from _bootstrap import canonical_paths, load_runtime_config, ...
try:
    from scripts.project_layout import *  # type: ignore[misc]  # noqa: E402,F401,F403
    from scripts.project_layout import (  # noqa: E402  — explicit names for IDE support
        ASSETS_DIR,
        CONFIG_DIR,
        CONTENT_CONFIG_DIR,
        DEFAULT_RUNTIME_CONFIG_PATH,
        DOCS_DIR,
        INTEGRATIONS_CONFIG_DIR,
        LOCAL_DIR,
        OPS_DIR,
        PREFERRED_RUNTIME_CONFIG_PATH,
        RUNTIME_CONFIG_DIR,
        RUNTIME_EXAMPLE_CONFIG_PATH,
        VAR_DIR,
        canonical_paths,
        deep_merge,
        default_runtime_config,
        expand_config_value,
        load_runtime_config,
    )
except ModuleNotFoundError:
    from project_layout import *  # noqa: E402,F401,F403
    from project_layout import (  # noqa: E402  — explicit names for IDE support
        ASSETS_DIR,
        CONFIG_DIR,
        CONTENT_CONFIG_DIR,
        DEFAULT_RUNTIME_CONFIG_PATH,
        DOCS_DIR,
        INTEGRATIONS_CONFIG_DIR,
        LOCAL_DIR,
        OPS_DIR,
        PREFERRED_RUNTIME_CONFIG_PATH,
        RUNTIME_CONFIG_DIR,
        RUNTIME_EXAMPLE_CONFIG_PATH,
        VAR_DIR,
        canonical_paths,
        deep_merge,
        default_runtime_config,
        expand_config_value,
        load_runtime_config,
    )
