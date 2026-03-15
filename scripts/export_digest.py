#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any
from xml.sax.saxutils import escape

from common import ensure_parent_dir, keyword_hits, load_yaml_file, parse_datetime_guess, read_jsonl

STAGE_LABELS = {
    "journal": "Published Papers",
    "preprint": "Preprints",
}

CATEGORY_LABELS = {
    "omics": "Omics",
    "gene-function-regulation": "Gene Function And Regulation",
    "genome-editing-breeding": "Genome Editing And Breeding",
    "protein-structure-function": "Protein Structure And Function",
    "ai-computational-biology": "AI And Computational Biology",
    "methods-datasets-resources": "Methods, Datasets And Resources",
    "plant-biology": "Plant Biology",
    "cell-development-signaling": "Cell Development And Signaling",
    "microbe-immunity": "Microbe And Immunity",
    "other": "Other",
}

DISPLAY_BUCKETS = [
    ("top-plant", "Top Plant Highlights", "顶刊中的植物学与作物研究优先展示。"),
    ("top-journals", "Top Journals", "CNS、NG、NP 等优先展示。"),
    ("plant-priority", "Plant Priority", "植物学与作物研究优先展示。"),
    ("ai-priority", "AI And Computational Biology", "AI 相关条目不做额外筛选。"),
    ("other-biology", "Other Biology", "其余符合范围的生物学研究。"),
    ("deferred-gene-function", "Gene Function (Non-Plant, Deferred)", "非植物基因功能研究后置汇总。"),
]

BUCKET_ORDER = {bucket_id: index for index, (bucket_id, _, _) in enumerate(DISPLAY_BUCKETS)}


def column_letter(index: int) -> str:
    letters = []
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def snippet(text: str, limit: int = 240) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def safe_value(record: dict[str, Any], key: str) -> str:
    value = record.get(key, "")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def format_publish_date(value: str) -> str:
    parsed = parse_datetime_guess(value)
    if parsed is None:
        return "Publish date unavailable"
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def build_display_context(rules: dict[str, Any]) -> dict[str, set[str]]:
    display_priority = rules.get("display_priority", {})
    visual_filters = rules.get("visual_filters", {})
    return {
        "default_grouping_mode": display_priority.get("default_grouping_mode", "journal"),
        "top_journal_source_ids": set(display_priority.get("top_journal_source_ids", [])),
        "journal_order_source_ids": list(display_priority.get("journal_order_source_ids", [])),
        "journal_order_rank": {
            source_id: index for index, source_id in enumerate(display_priority.get("journal_order_source_ids", []))
        },
        "plant_priority_groups": set(display_priority.get("plant_priority_groups", [])),
        "deferred_category_ids": set(display_priority.get("deferred_category_ids", [])),
        "non_deferred_category_ids": set(display_priority.get("non_deferred_category_ids", [])),
        "attachment_only_source_ids": set(visual_filters.get("attachment_only_source_ids", [])),
        "attachment_only_keywords": list(visual_filters.get("attachment_only_keywords", [])),
    }


def is_plant_priority(record: dict[str, Any], context: dict[str, set[str]]) -> bool:
    if record.get("group", "") in context["plant_priority_groups"]:
        return True
    text = " ".join(
        [
            safe_value(record, "journal").lower(),
            safe_value(record, "title_en").lower(),
            safe_value(record, "tags").lower(),
        ]
    )
    return any(token in text for token in ("plant", "crop", "arabidopsis", "auxin", "root", "leaf", "seed"))


def classify_display_bucket(record: dict[str, Any], context: dict[str, set[str]]) -> str:
    source_id = record.get("source_id", "")
    category = record.get("category", "other") or "other"
    plant_priority = is_plant_priority(record, context)
    if source_id in context["top_journal_source_ids"] and plant_priority:
        return "top-plant"
    if source_id in context["top_journal_source_ids"]:
        return "top-journals"
    if plant_priority:
        return "plant-priority"
    if category in context["non_deferred_category_ids"]:
        return "ai-priority"
    if category in context["deferred_category_ids"]:
        return "deferred-gene-function"
    return "other-biology"


def publish_sort_key(record: dict[str, Any]) -> tuple[float, str]:
    published = safe_value(record, "publish_date") or safe_value(record, "published_at")
    parsed = parse_datetime_guess(published)
    timestamp = parsed.timestamp() if parsed is not None else 0.0
    return (timestamp, safe_value(record, "title_en"))


def review_rank(record: dict[str, Any]) -> tuple[int, float]:
    decision = str(record.get("final_decision") or record.get("llm_decision") or "keep").lower()
    confidence_raw = record.get("llm_confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 1.0 if decision == "keep" else 0.0
    if decision == "review":
        return (1, confidence)
    if decision == "reject":
        return (2, confidence)
    return (0, -confidence)


def record_display_sort_key(record: dict[str, Any], context: dict[str, Any]) -> tuple[int, int, float, float, str]:
    timestamp, title = publish_sort_key(record)
    decision_bucket, confidence_bucket = review_rank(record)
    plant_bucket = 0 if is_plant_priority(record, context) else 1
    return (plant_bucket, decision_bucket, confidence_bucket, -timestamp, title.lower())


def journal_rank(records: list[dict[str, Any]], context: dict[str, Any]) -> tuple[int, int, str]:
    first = min(records, key=lambda record: record_display_sort_key(record, context))
    source_id = first.get("source_id", "")
    journal_name = safe_value(first, "journal")
    review_bucket = 1 if all(review_rank(record)[0] > 0 for record in records) else 0
    if source_id in context["journal_order_rank"]:
        return (review_bucket, 0, context["journal_order_rank"][source_id], journal_name.lower())
    if any(is_plant_priority(record, context) for record in records):
        return (review_bucket, 1, 0, journal_name.lower())
    non_plant_gene_only = all(
        record.get("category") in context["deferred_category_ids"] and not is_plant_priority(record, context)
        for record in records
    )
    if non_plant_gene_only:
        return (review_bucket, 3, 0, journal_name.lower())
    return (review_bucket, 2, 0, journal_name.lower())


def summarize_authors(record: dict[str, Any]) -> str:
    raw_authors = record.get("authors", [])
    if isinstance(raw_authors, str):
        authors = [raw_authors.strip()] if raw_authors.strip() else []
    else:
        authors = [str(author).strip() for author in raw_authors if str(author).strip()]
    if not authors:
        return ""
    if len(authors) <= 5:
        selected = authors
    else:
        selected = authors[:2] + authors[-3:]
    return "Authors: " + ", ".join(selected)


def should_hide_from_visual_digest(record: dict[str, Any], context: dict[str, Any]) -> bool:
    if record.get("source_id", "") not in context["attachment_only_source_ids"]:
        return False
    if is_plant_priority(record, context):
        return False
    if (record.get("category", "") or "") == "ai-computational-biology":
        return False
    text = " ".join(
        [
            safe_value(record, "journal"),
            safe_value(record, "title_en"),
            safe_value(record, "abstract"),
            safe_value(record, "tags"),
        ]
    ).lower()
    return bool(keyword_hits(text, context["attachment_only_keywords"]))


def render_record_card(record: dict[str, Any]) -> str:
    article_href = safe_value(record, "article_url") or (f"https://doi.org/{safe_value(record, 'doi')}" if safe_value(record, "doi") else "")
    doi_value = safe_value(record, "doi")
    doi_html = (
        f'<a href="{html.escape(f"https://doi.org/{doi_value}")}">DOI: {html.escape(doi_value)}</a>'
        if doi_value
        else '<span>DOI unavailable</span>'
    )
    title_en = html.escape(safe_value(record, "title_en"))
    title_zh = html.escape(safe_value(record, "title_zh"))
    authors_line = html.escape(summarize_authors(record))
    abstract = safe_value(record, "abstract")
    abstract_preview = html.escape(snippet(abstract, 220)) if abstract else "No abstract captured."
    abstract_full = html.escape(abstract) if abstract else "No abstract captured."
    journal = html.escape(safe_value(record, "journal"))
    stage = record.get("publication_stage", "journal") or "journal"
    category = record.get("category", "other") or "other"
    tags = safe_value(record, "tags")
    tag_html = f"<span>{html.escape(tags)}</span>" if tags else ""
    meta_parts = [
        f'<span class="badge badge-stage">{html.escape(STAGE_LABELS.get(stage, stage.title()))}</span>',
        f'<span class="badge badge-category">{html.escape(CATEGORY_LABELS.get(category, category.title()))}</span>',
        f"<span>{journal}</span>",
        f"<span>{html.escape(format_publish_date(safe_value(record, 'publish_date') or safe_value(record, 'published_at')))}</span>",
    ]
    if tag_html:
        meta_parts.append(tag_html)
    cta_html = '<span class="card-cta">Open Article</span>'
    author_html = f'<p class="card-authors">{authors_line}</p>' if authors_line else ""
    header_inner = (
        f'<p class="card-meta">{" · ".join(meta_parts)}</p>'
        f"<h3 class=\"card-title\">{title_en}</h3>"
        f"<p class=\"card-title-zh\">{title_zh}</p>"
        f"{author_html}"
        f"{cta_html}"
    )
    if article_href:
        header_html = f'<a class="card-main" href="{html.escape(article_href)}">{header_inner}</a>'
    else:
        header_html = f'<div class="card-main">{header_inner}</div>'
    abstract_html = (
        "<div class=\"abstract-shell\">"
        "<p class=\"abstract-label\">Abstract</p>"
        "<details>"
        f"<summary><span class=\"abstract-preview\">{abstract_preview}</span><span class=\"abstract-toggle\">点击展开阅读摘要</span></summary>"
        f"<div class=\"abstract-full\">{abstract_full}</div>"
        "</details>"
        "</div>"
    )
    article_link_html = (
        f'<a href="{html.escape(article_href)}">Article link</a>'
        if article_href
        else "<span>Article link unavailable</span>"
    )
    footer_html = f'<div class="card-footer">{doi_html} &nbsp;|&nbsp; {article_link_html}</div>'
    return f'<article class="card">{header_html}<div class="card-body">{abstract_html}{footer_html}</div></article>'


def render_priority_grouped_cards(records: list[dict[str, Any]], context: dict[str, Any]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[classify_display_bucket(record, context)].append(record)

    bucket_sections = []
    for bucket_id, bucket_label, bucket_description in DISPLAY_BUCKETS:
        bucket_records = sorted(grouped.get(bucket_id, []), key=lambda record: record_display_sort_key(record, context))
        if not bucket_records:
            continue
        cards = "".join(render_record_card(record) for record in bucket_records)
        bucket_sections.append(
            "<details class=\"group-details\">"
            f"<summary class=\"group-summary\">{html.escape(bucket_label)}"
            f"<span class=\"group-count\">{len(bucket_records)}</span></summary>"
            f"<p class=\"group-description\">{html.escape(bucket_description)}</p>"
            f"{cards}"
            "</details>"
        )
    return "".join(bucket_sections)


def render_journal_grouped_cards(records: list[dict[str, Any]], context: dict[str, Any]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    journal_names: dict[str, str] = {}
    for record in records:
        source_id = record.get("source_id", "")
        grouped[source_id].append(record)
        journal_names[source_id] = safe_value(record, "journal")

    ordered_groups = sorted(grouped.items(), key=lambda item: journal_rank(item[1], context))
    sections = []
    for source_id, journal_records in ordered_groups:
        ordered_records = sorted(journal_records, key=lambda record: record_display_sort_key(record, context))
        cards = "".join(render_record_card(record) for record in ordered_records)
        sections.append(
            "<details class=\"group-details\">"
            f"<summary class=\"group-summary\">{html.escape(journal_names.get(source_id, source_id))}"
            f"<span class=\"group-count\">{len(ordered_records)}</span></summary>"
            f"<p class=\"group-description\">按期刊分组，默认折叠。点击展开查看全部条目。</p>"
            f"{cards}"
            "</details>"
        )
    return "".join(sections)


def render_digest_cards(
    records: list[dict[str, Any]],
    template_text: str,
    rules: dict[str, Any],
    grouping_mode: str,
    style_override_css: str,
) -> str:
    context = build_display_context(rules)
    visible_records = [record for record in records if not should_hide_from_visual_digest(record, context)]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in visible_records:
        stage = record.get("publication_stage", "journal") or "journal"
        grouped[stage].append(record)

    sections = []
    stage_order = ["journal", "preprint"]
    ordered_stages = [stage for stage in stage_order if stage in grouped] + [stage for stage in sorted(grouped) if stage not in stage_order]
    for stage in ordered_stages:
        if grouping_mode == "priority":
            grouped_html = render_priority_grouped_cards(grouped[stage], context)
        else:
            grouped_html = render_journal_grouped_cards(grouped[stage], context)
        empty_html = '<div class="empty-state">No records available.</div>'
        sections.append(
            "<section class=\"section\">"
            f"<h2 class=\"section-title\">{html.escape(STAGE_LABELS.get(stage, stage.title()))}</h2>"
            f"<p class=\"section-subtitle\">{len(grouped[stage])} records</p>"
            f"{grouped_html or empty_html}"
            "</section>"
        )
    if not sections:
        sections.append('<section class="section"><div class="empty-state">No records matched the current visual filters in the digest body. Full records remain available in the attachments.</div></section>')
    greeting_template = rules.get("output_schema", {}).get("greeting_template", "{date}--祝你早上快乐--这是今日份的论文快看吧")
    greeting_line = greeting_template.format(date=datetime.now().strftime("%Y-%m-%d"))
    return Template(template_text).safe_substitute(
        sections="".join(sections),
        record_count=str(len(visible_records)),
        greeting_line=greeting_line,
        style_override_css=style_override_css,
    )


def render_html_table(records: list[dict[str, Any]], columns: list[str], template_text: str, style_override_css: str) -> str:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        stage = record.get("publication_stage", "journal") or "journal"
        category = record.get("category", "other") or "other"
        grouped[stage][category].append(record)

    sections = []
    stage_order = ["journal", "preprint"]
    ordered_stages = [stage for stage in stage_order if stage in grouped] + [stage for stage in sorted(grouped) if stage not in stage_order]
    for stage in ordered_stages:
        stage_sections = [f"<section class=\"section\"><h2 class=\"section-title\">{html.escape(STAGE_LABELS.get(stage, stage.title()))}</h2>"]
        for category in sorted(grouped[stage]):
            rows = []
            for record in grouped[stage][category]:
                cells = []
                for column in columns:
                    value = record.get(column, "")
                    if isinstance(value, list):
                        value = ", ".join(str(item) for item in value)
                    if column == "doi" and value:
                        display = html.escape(str(value))
                        href = html.escape(f"https://doi.org/{value}")
                        value_html = f'<a href="{href}">{display}</a>'
                    elif column == "article_url" and value:
                        href = html.escape(str(value))
                        value_html = f'<a href="{href}">link</a>'
                    else:
                        value_html = html.escape(str(value))
                    cells.append(f"<td>{value_html}</td>")
                rows.append("<tr>" + "".join(cells) + "</tr>")
            header_html = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
            stage_sections.append(
                f"<section class=\"section\"><h3>{html.escape(category)}</h3><table><thead><tr>{header_html}</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></section>"
            )
        stage_sections.append("</section>")
        sections.append("".join(stage_sections))
    if not sections:
        sections.append('<section class="section"><div class="empty-state">No records available.</div></section>')
    greeting_template = "待审队列"
    return Template(template_text).safe_substitute(
        sections="".join(sections),
        record_count=str(len(records)),
        greeting_line=greeting_template,
        style_override_css=style_override_css,
    )


def build_style_override_css(style_config: dict[str, Any]) -> str:
    if not isinstance(style_config, dict):
        return ""
    base_css = str(style_config.get("base_css", "") or "").strip()
    mobile_css = str(style_config.get("mobile_css", "") or "").strip()
    blocks: list[str] = []
    if base_css:
        blocks.append(base_css)
    if mobile_css:
        blocks.append(f"@media screen and (max-width: 640px) {{\n{mobile_css}\n}}")
    if not blocks:
        return ""
    return "\n" + "\n\n".join(blocks) + "\n"


def write_csv(path: str | Path, records: list[dict[str, Any]], columns: list[str]) -> None:
    path_obj = ensure_parent_dir(path)
    with path_obj.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            row = {}
            for column in columns:
                value = record.get(column, "")
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value)
                row[column] = value
            writer.writerow(row)


def write_xlsx(path: str | Path, records: list[dict[str, Any]], columns: list[str]) -> None:
    sheet_rows = [columns]
    for record in records:
        row = []
        for column in columns:
            value = record.get(column, "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            row.append(str(value))
        sheet_rows.append(row)

    rows_xml = []
    for row_index, row_values in enumerate(sheet_rows, start=1):
        cells = []
        for column_index, value in enumerate(row_values, start=1):
            ref = f"{column_letter(column_index)}{row_index}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        rows_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    workbook_files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>
""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="digest" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
""",
        "xl/styles.xml": """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>
""",
        "xl/worksheets/sheet1.xml": (
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>"""
            + "".join(rows_xml)
            + """</sheetData>
</worksheet>
"""
        ),
    }

    path_obj = ensure_parent_dir(path)
    with zipfile.ZipFile(path_obj, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in workbook_files.items():
            archive.writestr(name, content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export digest records to HTML, CSV, and XLSX.")
    parser.add_argument("--input", required=True, help="Localized input JSONL")
    parser.add_argument("--rules", required=True, help="Path to category_rules.yaml")
    parser.add_argument("--html-output", required=True, help="Output HTML file")
    parser.add_argument("--csv-output", required=True, help="Output CSV file")
    parser.add_argument("--xlsx-output", required=True, help="Output XLSX file")
    parser.add_argument("--template", required=True, help="HTML template file")
    parser.add_argument("--schema-key", default="output_schema", help="Schema section in category_rules.yaml")
    parser.add_argument("--grouping-mode", choices=["journal", "priority"], help="Override digest grouping mode")
    parser.add_argument("--style-config", help="Optional YAML file with CSS overrides for email styling")
    args = parser.parse_args()

    records = read_jsonl(Path(args.input))
    rules = load_yaml_file(args.rules) or {}
    schema = rules.get(args.schema_key, {})
    columns = schema.get(
        "required_columns",
        ["journal", "publish_date", "category", "title_en", "title_zh", "summary_zh", "abstract", "doi", "article_url", "tags"],
    )
    normalized_records: list[dict[str, Any]] = []
    for record in records:
        enriched = dict(record)
        if not enriched.get("publish_date"):
            enriched["publish_date"] = enriched.get("published_at", "")
        normalized_records.append(enriched)
    stage_sort = {"journal": 0, "preprint": 1}
    context = build_display_context(rules)
    grouping_mode = args.grouping_mode or str(context.get("default_grouping_mode", "journal"))
    normalized_records.sort(
        key=lambda item: (
            stage_sort.get(item.get("publication_stage", "journal"), 9),
            journal_rank([item], context) if grouping_mode == "journal" else (
                BUCKET_ORDER.get(classify_display_bucket(item, context), len(DISPLAY_BUCKETS)),
                0,
                safe_value(item, "journal").lower(),
            ),
            record_display_sort_key(item, context),
        ),
        reverse=False,
    )

    template_text = Path(args.template).read_text(encoding="utf-8")
    style_override_css = ""
    if args.style_config:
        style_override_css = build_style_override_css(load_yaml_file(args.style_config) or {})
    if args.schema_key == "output_schema":
        html_body = render_digest_cards(normalized_records, template_text, rules, grouping_mode, style_override_css)
    else:
        html_body = render_html_table(normalized_records, columns, template_text, style_override_css)
    ensure_parent_dir(args.html_output).write_text(html_body, encoding="utf-8")
    write_csv(args.csv_output, normalized_records, columns)
    write_xlsx(args.xlsx_output, normalized_records, columns)
    print(f"Exported {len(normalized_records)} records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
