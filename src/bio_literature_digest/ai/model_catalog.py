from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request
from typing import Any


def add_catalog_fallbacks(client: Any, ai_config: dict[str, Any], pinned: list[str]) -> list[str]:
    """Discover allowlisted new model IDs without overriding verified pinned models."""
    cfg = ai_config.get("model_discovery")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return pinned
    try:
        patterns = [re.compile(p) for p in cfg.get("allow_patterns", []) if isinstance(p, str) and len(p) < 200]
    except re.error:
        return pinned
    if not patterns:
        return pinned

    path = Path(__file__).resolve().parents[3] / "var/cache/nvidia-model-catalog.json"
    ttl = max(0, min(int(cfg.get("cache_ttl_seconds", 86400)), 604800))
    now = time.time()
    cached: dict[str, Any] = {}
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    ids = cached.get("models") if isinstance(cached.get("models"), list) else []
    age = now - float(cached.get("fetched_at", 0) or 0)
    if not (ids and 0 <= age < ttl):
        try:
            req = Request(
                urljoin(client.base_url.rstrip("/") + "/", "models"),
                headers={"Authorization": "Bearer " + client.api_key},
            )
            with client.opener(req, timeout=max(2, min(12, int(cfg.get("timeout_seconds", 6))))) as resp:
                obj = json.load(resp)
            new_ids = [x["id"] for x in obj.get("data", []) if isinstance(x, dict)
                       and isinstance(x.get("id"), str)
                       and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", x["id"])]
            if new_ids:
                ids = list(dict.fromkeys(new_ids))
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(".nvidia-model-catalog-" + str(os.getpid()) + ".tmp")
                try:
                    temp.write_text(json.dumps({"models": ids, "fetched_at": now}), encoding="utf-8")
                    temp.replace(path)
                finally:
                    temp.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass  # Catalog unavailability never blocks pinned inference.
    result = list(pinned)
    limit = max(len(result), min(12, int(cfg.get("max_candidates", 6))))
    for pattern in patterns:
        for model_id in sorted(ids, reverse=True):
            if len(result) >= limit:
                return result
            if isinstance(model_id, str) and model_id not in result and pattern.fullmatch(model_id):
                result.append(model_id)
    return result
