from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bio_literature_digest.ai import model_catalog


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class ModelCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "var")
        self.addCleanup(self.temp.cleanup)
        pretend_path = Path(self.temp.name) / "src/bio_literature_digest/ai/model_catalog.py"
        file_patch = mock.patch.object(model_catalog, "__file__", str(pretend_path))
        file_patch.start()
        self.addCleanup(file_patch.stop)
        self.config = {"model_discovery": {
            "enabled": True, "cache_ttl_seconds": 86400,
            "allow_patterns": [r"^nvidia/nemotron-[0-9.]+-bolt-[a-z0-9-]+$"],
            "max_candidates": 3,
        }}

    def test_pinned_priority_regex_filter_and_cache_reuse(self):
        calls = []
        def opener(req, timeout):
            calls.append(req.full_url)
            return FakeResponse({"data": [
                {"id": "nvidia/nemotron-3.6-bolt-e4b"},
                {"id": "nvidia/nemotron-3.6-embed-1b"},
            ]})
        client = SimpleNamespace(base_url="https://example.test/v1", api_key="fixture-key", opener=opener)
        first = model_catalog.add_catalog_fallbacks(client, self.config, ["fixed-primary"])
        second = model_catalog.add_catalog_fallbacks(client, self.config, ["fixed-primary"])
        self.assertEqual(first, ["fixed-primary", "nvidia/nemotron-3.6-bolt-e4b"])
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], "https://example.test/v1/models")
        cache = Path(self.temp.name) / "var/cache/nvidia-model-catalog.json"
        payload = json.loads(cache.read_text())
        self.assertEqual(sorted(payload), ["fetched_at", "models"])
        self.assertNotIn("fixture-key", cache.read_text())

    def test_api_failure_preserves_pinned_candidates(self):
        def fail(_req, timeout):
            raise TimeoutError("catalog unavailable")
        client = SimpleNamespace(base_url="https://example.test/v1", api_key="fixture-key", opener=fail)
        self.assertEqual(model_catalog.add_catalog_fallbacks(client, self.config, ["fixed-primary"]), ["fixed-primary"])


if __name__ == "__main__":
    unittest.main()
