#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from scripts.common import load_yaml_file, read_jsonl, write_jsonl
except ModuleNotFoundError:
    from common import load_yaml_file, read_jsonl, write_jsonl

try:
    from scripts._bootstrap import SKILL_DIR  # noqa: E402
except ModuleNotFoundError:
    from _bootstrap import SKILL_DIR  # noqa: E402

from bio_literature_digest.ai.screening import (  # noqa: E402
    is_uncertain_review_candidate,
    review_records_with_nvidia,
)


EDITORIAL_PREFIXES = ("Author Correction:", "Publisher Correction:", "Retraction:", "Erratum:", "Q&A with ")
EDITORIAL_TAGS = {"profile", "viewpoint", "q&a"}
HARD_REJECT_HINTS = {
    "solar cells",
    "frequency upconversion",
    "triboelectric",
    "peat",
    "bioregionalisation",
    "global change drivers",
    "ecological research",
}
STRONG_BIO_HINTS = {
    "metastasis",
    "embryo",
    "embryogenesis",
    "synapse",
    "mitochondria",
    "autophagy",
    "screening",
    "line-1",
    "mutation",
    "guard cell",
    "arabidopsis",
    "intestinal",
    "biofilm",
    "biofilms",
    "microbiota",
    "bile acid",
    "auxin",
    "enterocyte",
    "enterocytes",
    "senescent",
    "senescence",
    "circadian",
    "colon",
    "salivation",
    "brain stem",
    "nociceptive",
    "oxidative stress",
    "cd8",
    "t cell",
    "glioma",
    "theranostic",
    "diagnosis",
    "sensor",
    "electrochemical",
}


def fill_templates(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format(**variables)
    if isinstance(value, list):
        return [fill_templates(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: fill_templates(item, variables) for key, item in value.items()}
    return value


def json_path_get(payload: Any, path: str | None) -> Any:
    if not path:
        return None
    current = payload
    for raw_part in path.split("."):
        if current is None:
            return None
        if isinstance(current, list):
            current = current[int(raw_part)]
        else:
            current = current.get(raw_part)
    return current


def call_http_json(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    defaults = config.get("defaults", {})
    request_spec = config.get("request", {})
    api_key_env = config.get("secrets", {}).get("api_key_env", "")
    variables = {
        "title_en": record.get("title_en", ""),
        "abstract": record.get("abstract", ""),
        "journal": record.get("journal", ""),
        "publication_stage": record.get("publication_stage", ""),
        "category": record.get("category", ""),
        "tags_csv": ", ".join(record.get("tags", [])),
        "api_key": os.environ.get(api_key_env, ""),
    }
    method = (request_spec.get("method") or "POST").upper()
    url = fill_templates(request_spec["url"], variables)
    headers = fill_templates(request_spec.get("headers", {}), variables)
    query = fill_templates(request_spec.get("query", {}), variables)
    json_body = fill_templates(request_spec.get("json_body"), variables)
    encoded_url = url
    body_bytes = None
    if query:
        encoded_url = f"{url}?{urlencode(query, doseq=True)}"
    if json_body is not None:
        body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = Request(encoded_url, data=body_bytes, headers=headers, method=method)
    timeout_seconds = int(defaults.get("timeout_seconds", 30))
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    review_payload = json_path_get(payload, request_spec.get("response_json_path")) if request_spec.get("response_json_path") else payload
    return review_payload if isinstance(review_payload, dict) else payload


def placeholder_review(record: dict[str, Any]) -> dict[str, Any]:
    title = (record.get("title_en") or "").strip()
    category = record.get("category", "other")
    text = " ".join(
        str(part)
        for part in [record.get("title_en", ""), record.get("abstract", ""), " ".join(record.get("tags", []))]
        if part
    ).lower()
    tags = {str(tag).strip().lower() for tag in record.get("tags", [])}
    if title.startswith(EDITORIAL_PREFIXES):
        return {"decision": "reject", "confidence": 0.95, "reason": "editorial or correction item is outside the digest scope"}
    if tags & EDITORIAL_TAGS:
        return {"decision": "reject", "confidence": 0.9, "reason": "profile, viewpoint, or Q&A item is outside the digest scope"}
    if any(hint in text for hint in HARD_REJECT_HINTS):
        return {"decision": "reject", "confidence": 0.88, "reason": "topic appears outside the intended biology scope"}
    if category == "other":
        if any(hint in text for hint in STRONG_BIO_HINTS):
            return {"decision": "keep", "confidence": 0.83, "reason": "biology relevance is clear even though rule-based category remained other"}
        return {"decision": "review", "confidence": 0.62, "reason": "relevance or category remains ambiguous after rule-based classification"}
    if record.get("publication_stage") == "preprint":
        return {"decision": "keep", "confidence": 0.82, "reason": "preprint is biology-relevant but should remain marked as preprint"}
    return {"decision": "keep", "confidence": 0.92, "reason": "rule-based filtering and category assignment are consistent with biology scope"}


def command_review(command: str, record: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        input=json.dumps(record, ensure_ascii=False),
        text=True,
        shell=True,
        check=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("LLM review command must return a JSON object")
    return payload


def finalize_review(record: dict[str, Any], review_payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    defaults = config.get("defaults", {})
    keep_threshold = float(defaults.get("keep_threshold", 0.85))
    review_threshold = float(defaults.get("review_threshold", 0.60))
    decision = str(review_payload.get("decision", "review")).lower()
    confidence = float(review_payload.get("confidence", 0.5))
    reason = str(review_payload.get("reason", "no review reason provided"))
    category_override = review_payload.get("category_override")

    if decision not in {"keep", "review", "reject"}:
        if confidence >= keep_threshold:
            decision = "keep"
        elif confidence >= review_threshold:
            decision = "review"
        else:
            decision = "reject"

    annotated = dict(record)
    annotated["rule_decision"] = record.get("relevance_status", "keep")
    annotated["llm_decision"] = decision
    annotated["llm_confidence"] = round(confidence, 3)
    annotated["llm_reason"] = reason
    if category_override:
        annotated["category_original"] = record.get("category")
        annotated["category"] = category_override
        annotated["llm_category_override"] = category_override
    annotated["final_decision"] = decision
    return annotated


def nvidia_review_payloads(records: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    runtime_config = config.get("runtime", {}) if isinstance(config.get("runtime"), dict) else {}
    continue_on_error = bool(runtime_config.get("continue_on_error", True))
    payloads = [placeholder_review(record) for record in records]
    candidate_pairs = [(index, record) for index, record in enumerate(records) if is_uncertain_review_candidate(record)]
    if not candidate_pairs:
        return payloads

    candidate_records = [record for _, record in candidate_pairs]
    try:
        ai_payloads = review_records_with_nvidia(candidate_records, config)
    except Exception as error:
        if not continue_on_error:
            raise
        print(
            f"[review] provider=nvidia-chat failed for {len(candidate_records)} uncertain records "
            f"({type(error).__name__}: {error}); using placeholder review"
        )
        return payloads

    if len(ai_payloads) != len(candidate_records):
        if not continue_on_error:
            raise ValueError("NVIDIA review count does not match uncertain record count")
        print("[review] provider=nvidia-chat returned mismatched count; using placeholder review")
        return payloads

    for (index, _record), ai_payload in zip(candidate_pairs, ai_payloads):
        payloads[index] = ai_payload
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="Review filtered biology papers with an LLM or placeholder reviewer.")
    parser.add_argument("--input", required=True, help="Classified input JSONL")
    parser.add_argument("--output", required=True, help="Full reviewed audit JSONL")
    parser.add_argument("--keep-output", required=True, help="Records approved for digest output")
    parser.add_argument("--review-output", required=True, help="Records requiring human review")
    parser.add_argument("--reject-output", required=True, help="Records rejected after LLM review")
    parser.add_argument("--provider", choices=["placeholder", "command", "http-json", "nvidia-chat"], default="placeholder")
    parser.add_argument("--command", help="Shell command that reads one JSON record on stdin and returns JSON")
    parser.add_argument("--config", help="YAML config for provider-specific settings")
    args = parser.parse_args()

    if args.provider == "command" and not args.command:
        raise SystemExit("--command is required when --provider=command")
    if args.provider in {"http-json", "nvidia-chat"} and not args.config:
        raise SystemExit("--config is required when using an external review provider")

    config = load_yaml_file(args.config) or {} if args.config else {}
    records = read_jsonl(Path(args.input))
    reviewed: list[dict[str, Any]] = []
    keep_records: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []
    reject_records: list[dict[str, Any]] = []

    if args.provider == "nvidia-chat":
        prepared_payloads = nvidia_review_payloads(records, config)
    else:
        prepared_payloads = []

    for index, record in enumerate(records):
        if args.provider == "command":
            review_payload = command_review(args.command, record)
        elif args.provider == "http-json":
            raw_payload = call_http_json(record, config)
            response_fields = config.get("response_fields", {})
            review_payload = {
                "decision": json_path_get(raw_payload, response_fields.get("decision_path")) or raw_payload.get("decision"),
                "confidence": json_path_get(raw_payload, response_fields.get("confidence_path")) or raw_payload.get("confidence"),
                "reason": json_path_get(raw_payload, response_fields.get("reason_path")) or raw_payload.get("reason"),
                "category_override": json_path_get(raw_payload, response_fields.get("category_override_path"))
                if response_fields.get("category_override_path")
                else raw_payload.get("category_override"),
            }
        elif args.provider == "nvidia-chat":
            review_payload = prepared_payloads[index]
        else:
            review_payload = placeholder_review(record)

        annotated = finalize_review(record, review_payload, config)
        reviewed.append(annotated)
        if annotated["final_decision"] == "keep":
            keep_records.append(annotated)
        elif annotated["final_decision"] == "review":
            review_records.append(annotated)
        else:
            reject_records.append(annotated)

    write_jsonl(Path(args.output), reviewed)
    write_jsonl(Path(args.keep_output), keep_records)
    write_jsonl(Path(args.review_output), review_records)
    write_jsonl(Path(args.reject_output), reject_records)
    print(
        f"Reviewed {len(reviewed)} records: "
        f"{len(keep_records)} keep, {len(review_records)} review, {len(reject_records)} reject."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
