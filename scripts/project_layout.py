#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SRC_DIR = SKILL_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bio_literature_digest.config.runtime import (  # noqa: E402
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
    expand_config_value,
    fallback_runtime_config as default_runtime_config,
    load_runtime_config,
)
