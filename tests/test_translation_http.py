#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.project_layout import canonical_paths

try:
    from tests.helpers import load_script_module, FakeResponse
except ModuleNotFoundError:
    from helpers import load_script_module, FakeResponse

CANONICAL_PATHS = canonical_paths()


def load_module():
    return load_script_module("translate_and_summarize.py")


class TranslationHttpTest(unittest.TestCase):
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
                "prefix_template": "该文发表于《{journal}》，归类为\u201c{category_zh}\u201d。",
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
            "glossary_path": str(CANONICAL_PATHS["glossary"]),
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
                "prefix_template": "该文发表于《{journal}》，归类为\u201c{category_zh}\u201d。",
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

        http_calls: list[str] = []
        tencent_calls: list[str] = []

        def fake_http(record, _config):  # type: ignore[override]
            http_calls.append(record["title_en"])
            raise TimeoutError("http provider timed out")

        def fake_tencent(record, _config):  # type: ignore[override]
            tencent_calls.append(record["title_en"])
            return (f"ZH:{record['title_en']}", f"ZH:{record['abstract']}")

        with mock.patch.object(module, "localize_via_http_json", side_effect=fake_http):
            with mock.patch.object(module, "localize_via_tencent_tmt", side_effect=fake_tencent):
                localized = module.localize_records(records, "http-json", config, max_sentences=4)

        self.assertEqual(len(localized), 3)
        self.assertEqual(http_calls, ["Paper 1", "Paper 2"])
        self.assertEqual(tencent_calls, ["Paper 1", "Paper 2", "Paper 3"])
        self.assertEqual(localized[2]["title_zh"], "ZH:Paper 3")
        self.assertEqual(localized[2]["summary_zh"], "ZH:Abstract 3")

    def test_nvidia_chat_provider_uses_batch_result_and_glossary(self) -> None:
        module = load_module()
        records = [
            {
                "journal": "Nature Methods",
                "title_en": "A benchmark for single-cell workflows",
                "abstract": "A plant dataset benchmark.",
                "category": "methods-datasets-resources",
                "publication_stage": "journal",
            }
        ]
        config = {"glossary_path": str(CANONICAL_PATHS["glossary"])}
        ai_result = [
            {
                "title_zh": "单单元格 基准 工作流",
                "summary_zh": "单单元格 工作流 基准测试。第二句。第三句。",
            }
        ]

        with mock.patch.object(module, "translate_records_with_nvidia", return_value=ai_result) as mocked_translate:
            localized = module.localize_records(records, "nvidia-chat", config, max_sentences=2)

        mocked_translate.assert_called_once_with(records, config)
        self.assertEqual(localized[0]["title_zh"], "单细胞 基准测试 工作流程")
        self.assertEqual(localized[0]["summary_zh"], "单细胞 工作流程 基准测试。第二句。")

    def test_nvidia_chat_provider_falls_back_to_placeholder_when_unavailable(self) -> None:
        module = load_module()
        records = [
            {
                "journal": "Nature Methods",
                "title_en": "A benchmark for single-cell workflows",
                "abstract": "",
                "category": "methods-datasets-resources",
                "publication_stage": "journal",
            }
        ]
        config = {"runtime": {"continue_on_error": True}}

        with mock.patch.object(module, "translate_records_with_nvidia", side_effect=RuntimeError("quota exhausted")):
            localized = module.localize_records(records, "nvidia-chat", config, max_sentences=4)

        self.assertEqual(localized[0]["title_zh"], "A benchmark for single-cell workflows")
        self.assertIn("当前未抓取到可用摘要", localized[0]["summary_zh"])

    def test_nvidia_chat_provider_loads_tencent_fallback_config(self) -> None:
        module = load_module()
        records = [
            {
                "journal": "Nature Methods",
                "title_en": "A benchmark for single-cell workflows",
                "abstract": "A plant dataset benchmark.",
                "category": "methods-datasets-resources",
                "publication_stage": "journal",
            }
        ]

        with tempfile.TemporaryDirectory(prefix="bio-fallback-config-") as tmpdir:
            fallback_path = Path(tmpdir) / "translation_tencent_tmt.yaml"
            fallback_path.write_text(
                "\n".join(
                    [
                        "provider: tencent-tmt",
                        "tencent_tmt:",
                        "  source_lang: en",
                        "  target_lang: zh",
                        "summary:",
                        "  prefix_template: '该文发表于《{journal}》。'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            config = {
                "fallback_provider": "tencent-tmt",
                "fallback_config_path": str(fallback_path),
                "runtime": {"continue_on_error": True},
            }

            def fake_tencent(record, fallback_config):  # type: ignore[override]
                self.assertIn("tencent_tmt", fallback_config)
                return ("单细胞流程基准", "该文发表于《Nature Methods》。植物数据集基准。")

            with mock.patch.object(module, "translate_records_with_nvidia", side_effect=RuntimeError("missing key")):
                with mock.patch.object(module, "localize_via_tencent_tmt", side_effect=fake_tencent):
                    localized = module.localize_records(records, "nvidia-chat", config, max_sentences=4)

        self.assertEqual(localized[0]["title_zh"], "单细胞流程基准")
        self.assertIn("植物数据集基准", localized[0]["summary_zh"])


if __name__ == "__main__":
    unittest.main()
