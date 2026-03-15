#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os

from common import load_yaml_file, read_jsonl, write_jsonl


CATEGORY_LABELS = {
    "omics": "组学",
    "gene-function-regulation": "基因功能与调控",
    "genome-editing-breeding": "基因编辑与育种",
    "protein-structure-function": "蛋白结构与功能",
    "ai-computational-biology": "AI与计算生物学",
    "methods-datasets-resources": "方法、数据与资源",
    "plant-biology": "植物生物学",
    "cell-development-signaling": "细胞、发育与信号",
    "microbe-immunity": "微生物与免疫",
    "other": "其他",
}

STAGE_LABELS = {
    "journal": "正式发表",
    "preprint": "预印本",
}

_LAST_TENCENT_REQUEST_TS = 0.0
_LAST_GOOGLE_REQUEST_TS = 0.0


def load_glossary(config: dict[str, Any]) -> dict[str, Any]:
    glossary_path = config.get("glossary_path")
    if not glossary_path:
        return {}
    glossary = load_yaml_file(glossary_path) or {}
    return glossary if isinstance(glossary, dict) else {}


def normalize_bio_translation(text: str, glossary: dict[str, Any]) -> str:
    output = text.strip()
    replacements = glossary.get("replacements", [])
    for item in replacements:
        source = str(item.get("source", ""))
        target = str(item.get("target", ""))
        if not source or not target:
            continue
        output = output.replace(source, target)
    output = re.sub(r"(基准测试)(?:基准测试|测试)+", r"\1", output)
    output = re.sub(r"(工作流程)(?:工作流程|流程)+", r"\1", output)
    output = re.sub(r"(单细胞)(?:单细胞)+", r"\1", output)
    output = re.sub(r"流程程+", "流程", output)
    output = re.sub(r"测试测试+", "测试", output)
    output = re.sub(r"\s+", " ", output).strip()
    return output


def normalize_bio_translation_with_trace(text: str, glossary: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    output = text.strip()
    changes: list[dict[str, str]] = []
    for item in glossary.get("replacements", []):
        source = str(item.get("source", ""))
        target = str(item.get("target", ""))
        if source and target and source in output:
            output = output.replace(source, target)
            changes.append({"source": source, "target": target})
    output = re.sub(r"(基准测试)(?:基准测试|测试)+", r"\1", output)
    output = re.sub(r"(工作流程)(?:工作流程|流程)+", r"\1", output)
    output = re.sub(r"(单细胞)(?:单细胞)+", r"\1", output)
    output = re.sub(r"流程程+", "流程", output)
    output = re.sub(r"测试测试+", "测试", output)
    output = re.sub(r"\s+", " ", output).strip()
    return output, changes


def build_placeholder(record: dict[str, Any]) -> tuple[str, str]:
    category_label = CATEGORY_LABELS.get(record.get("category", "other"), "其他")
    stage_label = STAGE_LABELS.get(record.get("publication_stage", "journal"), "正式发表")
    title_en = record.get("title_en", "")
    journal = record.get("journal", "")
    abstract = record.get("abstract", "")
    title_zh = title_en
    if abstract:
        summary = (
            f"该文来源为《{journal}》{stage_label}条目，归类为“{category_label}”。"
            f"当前未配置自动中文翻译模型，建议根据摘要进一步润色。"
            f"摘要显示研究重点与“{title_en}”相关。"
        )
    else:
        summary = (
            f"该文来源为《{journal}》{stage_label}条目，归类为“{category_label}”。"
            "当前未抓取到可用摘要，后续需补充标题翻译与中文总结。"
        )
    return title_zh, summary


def run_external_command(command: str, record: dict[str, Any]) -> tuple[str, str]:
    completed = subprocess.run(
        command,
        input=json.dumps(record, ensure_ascii=False),
        text=True,
        shell=True,
        check=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    return payload["title_zh"], payload["summary_zh"]


def fill_templates(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format(**variables)
    if isinstance(value, list):
        return [fill_templates(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: fill_templates(item, variables) for key, item in value.items()}
    return value


def json_path_get(payload: Any, path: str) -> Any:
    current = payload
    for raw_part in path.split("."):
        if isinstance(current, list):
            current = current[int(raw_part)]
        else:
            current = current[raw_part]
    return current


def call_http_json(spec: dict[str, Any], text: str, source_lang: str, target_lang: str, timeout_seconds: int) -> str:
    variables = {
        "text": text,
        "source_lang": source_lang,
        "target_lang": target_lang,
    }
    method = (spec.get("method") or "GET").upper()
    url = fill_templates(spec["url"], variables)
    headers = fill_templates(spec.get("headers", {}), variables)
    query = fill_templates(spec.get("query", {}), variables)
    json_body = fill_templates(spec.get("json_body"), variables)
    encoded_url = url
    body_bytes = None
    if query:
        encoded_url = f"{url}?{urlencode(query, doseq=True)}"
    if json_body is not None:
        body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = Request(encoded_url, data=body_bytes, headers=headers, method=method)
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    value = json_path_get(payload, spec["response_json_path"])
    if not isinstance(value, str):
        raise ValueError("translation response_json_path must resolve to a string")
    return value.strip()


def _respect_rate_limit(last_request_attr: str, min_interval_seconds: float) -> None:
    if min_interval_seconds <= 0:
        return
    now = time.monotonic()
    last_request_ts = globals().get(last_request_attr, 0.0)
    wait_seconds = min_interval_seconds - (now - last_request_ts)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    globals()[last_request_attr] = time.monotonic()


def call_google_translate_basic_v2(text: str, config: dict[str, Any], source_lang: str, target_lang: str) -> str:
    google_config = config.get("google_basic_v2", {})
    endpoint = google_config.get("endpoint", "https://translation.googleapis.com/language/translate/v2")
    api_key = os.environ.get(google_config.get("api_key_env", "GOOGLE_TRANSLATE_API_KEY"), "")
    if not api_key:
        raise ValueError("Google Translate Basic v2 requires an API key environment variable")
    timeout_seconds = int(google_config.get("timeout_seconds", 20))
    min_interval_seconds = float(google_config.get("min_interval_seconds", 0.1))
    _respect_rate_limit("_LAST_GOOGLE_REQUEST_TS", min_interval_seconds)
    params = {
        "key": api_key,
        "q": text,
        "target": target_lang,
        "source": source_lang,
        "format": google_config.get("format", "text"),
        "model": google_config.get("model", "nmt"),
    }
    encoded_url = f"{endpoint}?{urlencode(params, doseq=True)}"
    request = Request(encoded_url, method="POST")
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    translations = (((payload or {}).get("data") or {}).get("translations") or [])
    if not translations:
        raise ValueError("Google Translate Basic v2 response missing translations")
    translated_text = translations[0].get("translatedText", "")
    if not isinstance(translated_text, str) or not translated_text.strip():
        raise ValueError("Google Translate Basic v2 response missing translatedText")
    return translated_text.strip()


def call_google_translate_basic_v2_with_retry(text: str, config: dict[str, Any], source_lang: str, target_lang: str) -> str:
    google_config = config.get("google_basic_v2", {})
    max_retries = int(google_config.get("max_retries", 5))
    retry_backoff_seconds = float(google_config.get("retry_backoff_seconds", 0.8))
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return call_google_translate_basic_v2(text, config, source_lang, target_lang)
        except Exception as error:  # urllib may raise various HTTP errors
            last_error = error
            message = str(error)
            if not any(token in message for token in ("429", "rateLimitExceeded", "userRateLimitExceeded", "quota")) or attempt >= max_retries:
                raise
            time.sleep(retry_backoff_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise ValueError("Google Translate Basic v2 translation failed without a specific error")


def _tc3_sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def call_tencent_tmt(text: str, config: dict[str, Any], source_lang: str, target_lang: str) -> str:
    tencent_config = config.get("tencent_tmt", {})
    secret_id = os.environ.get(tencent_config.get("secret_id_env", "TENCENT_TMT_SECRET_ID"), "")
    secret_key = os.environ.get(tencent_config.get("secret_key_env", "TENCENT_TMT_SECRET_KEY"), "")
    token = os.environ.get(tencent_config.get("token_env", ""), "") if tencent_config.get("token_env") else ""
    if not secret_id or not secret_key:
        raise ValueError("Tencent TMT requires SecretId and SecretKey environment variables")

    host = tencent_config.get("host", "tmt.tencentcloudapi.com")
    endpoint = tencent_config.get("endpoint", f"https://{host}/")
    service = tencent_config.get("service", "tmt")
    action = tencent_config.get("action", "TextTranslate")
    version = tencent_config.get("version", "2018-03-21")
    region = tencent_config.get("region", "ap-beijing")
    project_id = int(tencent_config.get("project_id", 0))
    untranslated_text = tencent_config.get("untranslated_text")
    timeout_seconds = int(tencent_config.get("timeout_seconds", 20))
    timestamp = int(tencent_config.get("timestamp_override", time.time()))
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

    payload: dict[str, Any] = {
        "SourceText": text,
        "Source": source_lang,
        "Target": target_lang,
        "ProjectId": project_id,
    }
    if untranslated_text:
        payload["UntranslatedText"] = untranslated_text

    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            "",
            canonical_headers,
            signed_headers,
            hashed_payload,
        ]
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _tc3_sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _tc3_sign(secret_date, service)
    secret_signing = _tc3_sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Version": version,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Region": region,
    }
    if token:
        headers["X-TC-Token"] = token

    min_interval_seconds = float(tencent_config.get("min_interval_seconds", 0.25))
    _respect_rate_limit("_LAST_TENCENT_REQUEST_TS", min_interval_seconds)
    request = Request(endpoint, data=payload_json.encode("utf-8"), method="POST")
    for key, value in headers.items():
        request.add_header(key, str(value))
    with urlopen(request, timeout=timeout_seconds) as response:
        payload_response = json.loads(response.read().decode("utf-8"))

    if "Response" not in payload_response:
        raise ValueError("Tencent TMT response missing Response field")
    response_payload = payload_response["Response"]
    if "Error" in response_payload:
        error = response_payload["Error"]
        raise ValueError(f"Tencent TMT error: {error.get('Code')} {error.get('Message')}")
    target_text = response_payload.get("TargetText", "")
    if not isinstance(target_text, str) or not target_text.strip():
        raise ValueError("Tencent TMT response missing TargetText")
    return target_text.strip()


def call_tencent_tmt_with_retry(text: str, config: dict[str, Any], source_lang: str, target_lang: str) -> str:
    tencent_config = config.get("tencent_tmt", {})
    max_retries = int(tencent_config.get("max_retries", 5))
    retry_backoff_seconds = float(tencent_config.get("retry_backoff_seconds", 0.8))
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return call_tencent_tmt(text, config, source_lang, target_lang)
        except ValueError as error:
            last_error = error
            message = str(error)
            if "RequestLimitExceeded" not in message or attempt >= max_retries:
                raise
            time.sleep(retry_backoff_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise ValueError("Tencent TMT translation failed without a specific error")


def build_summary_from_translation(record: dict[str, Any], translated_abstract: str, summary_config: dict[str, Any]) -> str:
    category_label = CATEGORY_LABELS.get(record.get("category", "other"), "其他")
    stage_label = STAGE_LABELS.get(record.get("publication_stage", "journal"), "正式发表")
    prefix_template = summary_config.get("prefix_template", "该文发表于《{journal}》，归类为“{category_zh}”。")
    prefix = prefix_template.format(
        journal=record.get("journal", ""),
        category_zh=category_label,
        publication_stage_zh=stage_label,
    )
    sentences = [part.strip() for part in translated_abstract.replace("!", "。").replace("！", "。").replace("?", "。").split("。") if part.strip()]
    body = "。".join(sentences[:2])
    if body:
        return f"{prefix}{body}。"
    return prefix


def localize_via_http_json(record: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    glossary = load_glossary(config)
    defaults = config.get("defaults", {})
    timeout_seconds = int(defaults.get("timeout_seconds", 20))
    source_lang = defaults.get("source_lang", "en")
    target_lang = defaults.get("target_lang", "zh-CN")
    title_zh, _ = normalize_bio_translation_with_trace(
        call_http_json(config["title_translation"], record.get("title_en", ""), source_lang, target_lang, timeout_seconds),
        glossary,
    )
    abstract = record.get("abstract", "")
    summary_config = config.get("summary", {})
    if abstract:
        translated_abstract, _ = normalize_bio_translation_with_trace(
            call_http_json(config["abstract_translation"], abstract, source_lang, target_lang, timeout_seconds),
            glossary,
        )
        summary_zh = build_summary_from_translation(record, translated_abstract, summary_config)
    else:
        category_label = CATEGORY_LABELS.get(record.get("category", "other"), "其他")
        stage_label = STAGE_LABELS.get(record.get("publication_stage", "journal"), "正式发表")
        fallback_template = summary_config.get(
            "fallback_without_abstract",
            "该文来源为《{journal}》{publication_stage_zh}条目，归类为“{category_zh}”。当前未抓取到可用摘要，建议后续人工补充中文总结。",
        )
        summary_zh = fallback_template.format(
            journal=record.get("journal", ""),
            category_zh=category_label,
            publication_stage_zh=stage_label,
        )
    return title_zh, summary_zh


def localize_via_tencent_tmt(record: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    glossary = load_glossary(config)
    tencent_config = config.get("tencent_tmt", {})
    source_lang = tencent_config.get("source_lang", "en")
    target_lang = tencent_config.get("target_lang", "zh")
    title_zh, _ = normalize_bio_translation_with_trace(
        call_tencent_tmt_with_retry(record.get("title_en", ""), config, source_lang, target_lang),
        glossary,
    )
    abstract = record.get("abstract", "")
    summary_config = config.get("summary", {})
    if abstract:
        translated_abstract, _ = normalize_bio_translation_with_trace(
            call_tencent_tmt_with_retry(abstract, config, source_lang, target_lang),
            glossary,
        )
        summary_zh = build_summary_from_translation(record, translated_abstract, summary_config)
    else:
        category_label = CATEGORY_LABELS.get(record.get("category", "other"), "其他")
        stage_label = STAGE_LABELS.get(record.get("publication_stage", "journal"), "正式发表")
        fallback_template = summary_config.get(
            "fallback_without_abstract",
            "该文来源为《{journal}》{publication_stage_zh}条目，归类为“{category_zh}”。当前未抓取到可用摘要，建议后续人工补充中文总结。",
        )
        summary_zh = fallback_template.format(
            journal=record.get("journal", ""),
            category_zh=category_label,
            publication_stage_zh=stage_label,
        )
    return title_zh, summary_zh


def localize_via_google_basic_v2(record: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    glossary = load_glossary(config)
    google_config = config.get("google_basic_v2", {})
    source_lang = google_config.get("source_lang", "en")
    target_lang = google_config.get("target_lang", "zh-CN")
    summary_config = config.get("summary", {})
    fallback_provider = str(config.get("fallback_provider", "")).strip().lower()
    try:
        title_zh, _ = normalize_bio_translation_with_trace(
            call_google_translate_basic_v2_with_retry(record.get("title_en", ""), config, source_lang, target_lang),
            glossary,
        )
        abstract = record.get("abstract", "")
        if abstract:
            translated_abstract, _ = normalize_bio_translation_with_trace(
                call_google_translate_basic_v2_with_retry(abstract, config, source_lang, target_lang),
                glossary,
            )
            summary_zh = build_summary_from_translation(record, translated_abstract, summary_config)
        else:
            category_label = CATEGORY_LABELS.get(record.get("category", "other"), "其他")
            stage_label = STAGE_LABELS.get(record.get("publication_stage", "journal"), "正式发表")
            fallback_template = summary_config.get(
                "fallback_without_abstract",
                "归类为“{category_zh}”的{publication_stage_zh}条目。当前未抓取到可用摘要，建议后续人工补充中文总结。",
            )
            summary_zh = fallback_template.format(
                journal=record.get("journal", ""),
                category_zh=category_label,
                publication_stage_zh=stage_label,
            )
        return title_zh, summary_zh
    except Exception:
        if fallback_provider == "tencent-tmt":
            return localize_via_tencent_tmt(record, config)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Add Chinese title and summary fields.")
    parser.add_argument("--input", required=True, help="Classified input JSONL")
    parser.add_argument("--output", required=True, help="Localized output JSONL")
    parser.add_argument("--rules", required=True, help="Path to category_rules.yaml")
    parser.add_argument(
        "--provider",
        choices=["placeholder", "command", "http-json", "tencent-tmt", "google-basic-v2"],
        default="placeholder",
        help="Summary generation backend",
    )
    parser.add_argument("--command", help="Shell command that reads one JSON record on stdin and returns JSON")
    parser.add_argument("--config", help="YAML config for provider-specific settings")
    args = parser.parse_args()

    if args.provider == "command" and not args.command:
        raise SystemExit("--command is required when --provider=command")
    if args.provider in {"http-json", "tencent-tmt", "google-basic-v2"} and not args.config:
        raise SystemExit("--config is required when --provider=http-json, --provider=tencent-tmt, or --provider=google-basic-v2")

    rules = load_yaml_file(args.rules) or {}
    provider_config = load_yaml_file(args.config) or {} if args.config else {}
    summary_requirements = rules.get("output_schema", {}).get("summary_requirements", {})
    max_sentences = summary_requirements.get("max_sentences", 4)

    records = read_jsonl(Path(args.input))
    output: list[dict[str, Any]] = []
    for record in records:
        if args.provider == "command":
            title_zh, summary_zh = run_external_command(args.command, record)
        elif args.provider == "http-json":
            title_zh, summary_zh = localize_via_http_json(record, provider_config)
        elif args.provider == "tencent-tmt":
            title_zh, summary_zh = localize_via_tencent_tmt(record, provider_config)
        elif args.provider == "google-basic-v2":
            title_zh, summary_zh = localize_via_google_basic_v2(record, provider_config)
        else:
            title_zh, summary_zh = build_placeholder(record)

        sentences = [part.strip() for part in summary_zh.replace("！", "。").replace("?", "。").split("。") if part.strip()]
        if len(sentences) > max_sentences:
            summary_zh = "。".join(sentences[:max_sentences]) + "。"

        localized = dict(record)
        localized["title_zh"] = title_zh
        localized["summary_zh"] = summary_zh
        output.append(localized)

    write_jsonl(Path(args.output), output)
    print(f"Localized {len(output)} records with provider={args.provider}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
