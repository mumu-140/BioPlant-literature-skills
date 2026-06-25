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

try:
    from scripts.common import load_yaml_file, read_jsonl, write_jsonl
except ModuleNotFoundError:
    from common import load_yaml_file, read_jsonl, write_jsonl
try:
    from scripts._bootstrap import expand_config_value  # noqa: E402
except ModuleNotFoundError:
    from _bootstrap import expand_config_value  # noqa: E402


from bio_literature_digest.ai.translation import translate_records_with_nvidia  # noqa: E402


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


def load_glossary(config: dict[str, Any]) -> dict[str, Any]:
    glossary_path = expand_config_value(config.get("glossary_path"))
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


def normalize_provider_name(value: Any) -> str:
    return str(value or "").strip().lower()


def summarize_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    if not message:
        return error.__class__.__name__
    return f"{error.__class__.__name__}: {message}"


def resolve_fallback_config_path(config: dict[str, Any], fallback_provider: str) -> str:
    provider_key = fallback_provider.replace("-", "_")
    fallback_configs = config.get("fallback_configs", {})
    if isinstance(fallback_configs, dict):
        explicit_path = fallback_configs.get(fallback_provider) or fallback_configs.get(provider_key)
        if explicit_path:
            return str(explicit_path)

    explicit_path = config.get(f"{provider_key}_config_path")
    if explicit_path:
        return str(explicit_path)
    if config.get("fallback_provider") == fallback_provider and config.get("fallback_config_path"):
        return str(config["fallback_config_path"])
    return ""


def load_fallback_provider_config(config: dict[str, Any], fallback_provider: str) -> dict[str, Any]:
    path = resolve_fallback_config_path(config, fallback_provider)
    if not path:
        return config

    resolved_path = Path(str(expand_config_value(path))).resolve()
    fallback_config = load_yaml_file(resolved_path) or {}
    if not isinstance(fallback_config, dict):
        raise ValueError(f"Fallback config must be a mapping: {resolved_path}")

    merged = dict(fallback_config)
    for shared_key in ("glossary_path", "runtime"):
        if shared_key in config and shared_key not in merged:
            merged[shared_key] = config[shared_key]
    return merged


def apply_summary_sentence_limit(summary_zh: str, max_sentences: int) -> str:
    sentences = [part.strip() for part in summary_zh.replace("！", "。").replace("?", "。").split("。") if part.strip()]
    if len(sentences) > max_sentences:
        return "。".join(sentences[:max_sentences]) + "。"
    return summary_zh


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


def localize_record(
    record: dict[str, Any],
    provider: str,
    config: dict[str, Any],
    *,
    command: str | None = None,
) -> tuple[str, str]:
    if provider == "command":
        if not command:
            raise ValueError("command provider requires --command")
        return run_external_command(command, record)
    if provider == "http-json":
        return localize_via_http_json(record, config)
    if provider == "tencent-tmt":
        return localize_via_tencent_tmt(record, config)
    return build_placeholder(record)


def normalize_nvidia_localization(
    record: dict[str, Any],
    localized_fields: dict[str, Any],
    glossary: dict[str, Any],
    max_sentences: int,
) -> tuple[str, str]:
    title_raw = str(localized_fields.get("title_zh") or record.get("title_en", ""))
    summary_raw = str(localized_fields.get("summary_zh") or "")
    title_zh, _ = normalize_bio_translation_with_trace(title_raw, glossary)
    summary_zh, _ = normalize_bio_translation_with_trace(summary_raw, glossary)
    if not summary_zh:
        _, summary_zh = build_placeholder(record)
    return title_zh, apply_summary_sentence_limit(summary_zh, max_sentences)


def localize_records(
    records: list[dict[str, Any]],
    provider: str,
    config: dict[str, Any],
    *,
    command: str | None = None,
    max_sentences: int = 4,
    output_path: Path | None = None,
) -> list[dict[str, Any]]:
    runtime_config = config.get("runtime", {}) if isinstance(config.get("runtime"), dict) else {}
    continue_on_error = bool(runtime_config.get("continue_on_error", True))
    disable_primary_after_failures = max(1, int(runtime_config.get("disable_primary_after_failures", 2)))
    checkpoint_every_records = max(1, int(runtime_config.get("checkpoint_every_records", 1)))

    primary_provider = normalize_provider_name(provider) or "placeholder"
    fallback_provider = ""
    if primary_provider == "nvidia-chat":
        fallback_provider = normalize_provider_name(config.get("fallback_provider")) or "placeholder"
    elif primary_provider not in {"placeholder", "command"}:
        fallback_provider = normalize_provider_name(config.get("fallback_provider"))
    if fallback_provider == primary_provider:
        fallback_provider = ""
    active_provider = primary_provider
    consecutive_primary_failures = 0
    output: list[dict[str, Any]] = []

    if primary_provider == "nvidia-chat":
        try:
            translated = translate_records_with_nvidia(records, config)
            if len(translated) != len(records):
                raise ValueError("NVIDIA batch translation count does not match input count")
            glossary = load_glossary(config)
            for index, (record, localized_fields) in enumerate(zip(records, translated), start=1):
                title_zh, summary_zh = normalize_nvidia_localization(record, localized_fields, glossary, max_sentences)
                localized = dict(record)
                localized["title_zh"] = title_zh
                localized["summary_zh"] = summary_zh
                output.append(localized)
                print(f"[translate] localized record {index}/{len(records)} using provider=nvidia-chat")
            if output_path is not None:
                write_jsonl(output_path, output)
            return output
        except Exception as error:
            if not continue_on_error:
                raise
            print(
                f"[translate] provider=nvidia-chat failed for batch of {len(records)} records "
                f"({summarize_error(error)}); fallback={fallback_provider}"
            )
            if fallback_provider and fallback_provider != "placeholder":
                try:
                    fallback_config = load_fallback_provider_config(config, fallback_provider)
                except Exception as fallback_config_error:
                    print(
                        f"[translate] fallback provider={fallback_provider} config failed "
                        f"({summarize_error(fallback_config_error)}); using current config"
                    )
                    fallback_config = config
                return localize_records(
                    records,
                    fallback_provider,
                    fallback_config,
                    command=command,
                    max_sentences=max_sentences,
                    output_path=output_path,
                )
            output = []
            for index, record in enumerate(records, start=1):
                title_zh, summary_zh = build_placeholder(record)
                localized = dict(record)
                localized["title_zh"] = title_zh
                localized["summary_zh"] = apply_summary_sentence_limit(summary_zh, max_sentences)
                output.append(localized)
                print(f"[translate] localized record {index}/{len(records)} using provider=placeholder")
            if output_path is not None:
                write_jsonl(output_path, output)
            return output

    for index, record in enumerate(records, start=1):
        title = str(record.get("title_en", "")).strip() or "(untitled)"
        provider_for_record = active_provider
        used_provider = provider_for_record
        try:
            title_zh, summary_zh = localize_record(
                record,
                provider_for_record,
                config,
                command=command,
            )
            if provider_for_record == primary_provider:
                consecutive_primary_failures = 0
        except Exception as primary_error:
            if provider_for_record == primary_provider:
                consecutive_primary_failures += 1
            error_message = summarize_error(primary_error)
            if fallback_provider and provider_for_record == primary_provider:
                print(
                    f"[translate] primary provider={primary_provider} failed for record {index}/{len(records)} "
                    f"({title}): {error_message}; fallback={fallback_provider}"
                )
                try:
                    title_zh, summary_zh = localize_record(
                        record,
                        fallback_provider,
                        config,
                        command=command,
                    )
                    used_provider = fallback_provider
                except Exception as fallback_error:
                    fallback_message = summarize_error(fallback_error)
                    if not continue_on_error:
                        raise
                    print(
                        f"[translate] fallback provider={fallback_provider} also failed for record {index}/{len(records)} "
                        f"({title}): {fallback_message}; using placeholder"
                    )
                    title_zh, summary_zh = build_placeholder(record)
                    used_provider = "placeholder"
            elif continue_on_error:
                print(
                    f"[translate] provider={provider_for_record} failed for record {index}/{len(records)} "
                    f"({title}): {error_message}; using placeholder"
                )
                title_zh, summary_zh = build_placeholder(record)
                used_provider = "placeholder"
            else:
                raise

        if (
            primary_provider == active_provider
            and fallback_provider
            and consecutive_primary_failures >= disable_primary_after_failures
        ):
            active_provider = fallback_provider
            print(
                f"[translate] switching remaining records to fallback provider={fallback_provider} "
                f"after {consecutive_primary_failures} consecutive {primary_provider} failures"
            )

        localized = dict(record)
        localized["title_zh"] = title_zh
        localized["summary_zh"] = apply_summary_sentence_limit(summary_zh, max_sentences)
        output.append(localized)

        if output_path is not None and (index % checkpoint_every_records == 0 or index == len(records)):
            write_jsonl(output_path, output)
        print(f"[translate] localized record {index}/{len(records)} using provider={used_provider}")

    if output_path is not None and not records:
        write_jsonl(output_path, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Add Chinese title and summary fields.")
    parser.add_argument("--input", required=True, help="Classified input JSONL")
    parser.add_argument("--output", required=True, help="Localized output JSONL")
    parser.add_argument("--rules", required=True, help="Path to category_rules.yaml")
    parser.add_argument(
        "--provider",
        choices=["placeholder", "command", "http-json", "tencent-tmt", "nvidia-chat"],
        default="placeholder",
        help="Summary generation backend",
    )
    parser.add_argument("--command", help="Shell command that reads one JSON record on stdin and returns JSON")
    parser.add_argument("--config", help="YAML config for provider-specific settings")
    args = parser.parse_args()

    if args.provider == "command" and not args.command:
        raise SystemExit("--command is required when --provider=command")
    if args.provider in {"http-json", "tencent-tmt", "nvidia-chat"} and not args.config:
        raise SystemExit("--config is required when using an external summary provider")

    rules = load_yaml_file(args.rules) or {}
    provider_config = load_yaml_file(args.config) or {} if args.config else {}
    summary_requirements = rules.get("output_schema", {}).get("summary_requirements", {})
    max_sentences = summary_requirements.get("max_sentences", 4)

    records = read_jsonl(Path(args.input))
    output = localize_records(
        records,
        args.provider,
        provider_config,
        command=args.command,
        max_sentences=max_sentences,
        output_path=Path(args.output),
    )
    print(f"Localized {len(output)} records with provider={args.provider}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
