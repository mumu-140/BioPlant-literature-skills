#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "translate_and_summarize.py"


def load_module():
    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("translate_and_summarize_module", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load translate_and_summarize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class TranslationHttpTest(unittest.TestCase):
    def test_google_basic_v2_provider_localizes_title_and_summary(self) -> None:
        module = load_module()
        record = {
            "journal": "Nature Methods",
            "title_en": "A benchmark for single-cell annotation",
            "abstract": "This study benchmarks single-cell annotation workflows for plant datasets.",
            "category": "methods-datasets-resources",
            "publication_stage": "journal",
            "tags": ["single-cell", "benchmark"],
        }
        config = {
            "glossary_path": str(SKILL_DIR / "references" / "bio_translation_glossary.yaml"),
            "google_basic_v2": {
                "endpoint": "https://translation.googleapis.com/language/translate/v2",
                "api_key_env": "GOOGLE_TRANSLATE_API_KEY",
                "source_lang": "en",
                "target_lang": "zh-CN",
                "timeout_seconds": 5,
                "model": "nmt",
                "format": "text",
            },
            "summary": {
                "prefix_template": "",
            },
        }

        responses = [
            FakeResponse({"data": {"translations": [{"translatedText": "single-cell annotation 基准"}]}}),
            FakeResponse({"data": {"translations": [{"translatedText": "This study benchmarks single-cell annotation workflows for plant datasets."}]}}),
        ]

        with mock.patch.dict("os.environ", {"GOOGLE_TRANSLATE_API_KEY": "key"}, clear=False):
            with mock.patch.object(module, "urlopen", side_effect=responses) as mocked_urlopen:
                title_zh, summary_zh = module.localize_via_google_basic_v2(record, config)

        self.assertEqual(title_zh, "单细胞 annotation 基准测试")
        self.assertIn("This study benchmarks 单细胞 annotation workflows for plant datasets", summary_zh)
        first_request = mocked_urlopen.call_args_list[0].args[0]
        self.assertIn("translation.googleapis.com/language/translate/v2", first_request.full_url)
        self.assertIn("key=key", first_request.full_url)

    def test_http_json_provider_localizes_title_and_summary(self) -> None:
        module = load_module()
        record = {
            "journal": "Nature Methods",
            "title_en": "A benchmark for single-cell annotation",
            "abstract": "This study benchmarks single-cell annotation workflows for plant datasets.",
            "category": "methods-datasets-resources",
            "tags": ["single-cell", "benchmark"],
        }
        config = {
            "defaults": {"source_lang": "en", "target_lang": "zh-CN", "timeout_seconds": 5},
            "title_translation": {
                "method": "GET",
                "url": "https://example.invalid/translate",
                "query": {"text": "{text}", "from": "{source_lang}", "to": "{target_lang}"},
                "response_json_path": "data.translation",
            },
            "abstract_translation": {
                "method": "GET",
                "url": "https://example.invalid/translate",
                "query": {"text": "{text}", "from": "{source_lang}", "to": "{target_lang}"},
                "response_json_path": "data.translation",
            },
            "summary": {
                "mode": "translated-abstract",
                "prefix_template": "该文发表于《{journal}》，归类为“{category_zh}”。",
            },
        }

        responses = [
            FakeResponse({"data": {"translation": "ZH:A benchmark for single-cell annotation"}}),
            FakeResponse({"data": {"translation": "ZH:This study benchmarks single-cell annotation workflows for plant datasets."}}),
        ]

        with mock.patch.object(module, "urlopen", side_effect=responses):
            title_zh, summary_zh = module.localize_via_http_json(record, config)

        self.assertEqual(title_zh, "ZH:A benchmark for single-cell annotation")
        self.assertIn("该文发表于《Nature Methods》", summary_zh)
        self.assertIn("ZH:This study benchmarks single-cell annotation workflows for plant datasets", summary_zh)

    def test_tencent_tmt_provider_localizes_title_and_summary(self) -> None:
        module = load_module()
        record = {
            "journal": "Nature Methods",
            "title_en": "A benchmark for single-cell annotation",
            "abstract": "This study benchmarks single-cell annotation workflows for plant datasets.",
            "category": "methods-datasets-resources",
            "publication_stage": "journal",
            "tags": ["single-cell", "benchmark"],
        }
        config = {
            "glossary_path": str(SKILL_DIR / "references" / "bio_translation_glossary.yaml"),
            "tencent_tmt": {
                "endpoint": "https://tmt.tencentcloudapi.com/",
                "host": "tmt.tencentcloudapi.com",
                "service": "tmt",
                "action": "TextTranslate",
                "version": "2018-03-21",
                "region": "ap-beijing",
                "project_id": 0,
                "source_lang": "en",
                "target_lang": "zh",
                "timeout_seconds": 5,
                "secret_id_env": "TENCENT_TMT_SECRET_ID",
                "secret_key_env": "TENCENT_TMT_SECRET_KEY",
                "timestamp_override": 1700000000,
            },
            "summary": {
                "prefix_template": "该文发表于《{journal}》，归类为“{category_zh}”。",
            },
        }

        captured_requests = []

        def fake_urlopen(request, timeout=0):  # type: ignore[override]
            captured_requests.append((request, timeout))
            payload = {"Response": {"TargetText": "单单元格 基准 工作流"}}
            return FakeResponse(payload)

        with mock.patch.dict("os.environ", {"TENCENT_TMT_SECRET_ID": "id", "TENCENT_TMT_SECRET_KEY": "key"}, clear=False):
            with mock.patch.object(module, "urlopen", side_effect=fake_urlopen):
                title_zh, summary_zh = module.localize_via_tencent_tmt(record, config)

        self.assertEqual(title_zh, "单细胞 基准测试 工作流程")
        self.assertIn("该文发表于《Nature Methods》", summary_zh)
        self.assertEqual(len(captured_requests), 2)
        request, timeout = captured_requests[0]
        self.assertEqual(timeout, 5)
        self.assertEqual(request.full_url, "https://tmt.tencentcloudapi.com/")
        self.assertEqual(request.get_header("X-tc-action"), "TextTranslate")
        self.assertTrue(request.get_header("Authorization", "").startswith("TC3-HMAC-SHA256"))

    def test_localize_records_switches_remaining_records_to_fallback_after_primary_failures(self) -> None:
        module = load_module()
        records = [
            {
                "journal": "Nature Methods",
                "title_en": "Paper 1",
                "abstract": "Abstract 1",
                "category": "methods-datasets-resources",
                "publication_stage": "journal",
            },
            {
                "journal": "Nature Methods",
                "title_en": "Paper 2",
                "abstract": "Abstract 2",
                "category": "methods-datasets-resources",
                "publication_stage": "journal",
            },
            {
                "journal": "Nature Methods",
                "title_en": "Paper 3",
                "abstract": "Abstract 3",
                "category": "methods-datasets-resources",
                "publication_stage": "journal",
            },
        ]
        config = {
            "fallback_provider": "tencent-tmt",
            "runtime": {
                "disable_primary_after_failures": 2,
                "checkpoint_every_records": 1,
            },
        }

        google_calls: list[str] = []
        tencent_calls: list[str] = []

        def fake_google(record, _config, *, allow_fallback=True):  # type: ignore[override]
            google_calls.append(record["title_en"])
            raise TimeoutError("google timed out")

        def fake_tencent(record, _config):  # type: ignore[override]
            tencent_calls.append(record["title_en"])
            return (f"ZH:{record['title_en']}", f"ZH:{record['abstract']}")

        with mock.patch.object(module, "localize_via_google_basic_v2", side_effect=fake_google):
            with mock.patch.object(module, "localize_via_tencent_tmt", side_effect=fake_tencent):
                localized = module.localize_records(records, "google-basic-v2", config, max_sentences=4)

        self.assertEqual(len(localized), 3)
        self.assertEqual(google_calls, ["Paper 1", "Paper 2"])
        self.assertEqual(tencent_calls, ["Paper 1", "Paper 2", "Paper 3"])
        self.assertEqual(localized[2]["title_zh"], "ZH:Paper 3")
        self.assertEqual(localized[2]["summary_zh"], "ZH:Abstract 3")


if __name__ == "__main__":
    unittest.main()
