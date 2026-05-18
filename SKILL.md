---
name: bio-literature-digest
description: Build, operate, or refine a daily literature-digest workflow for biology, plant biology, and AI-for-bio papers. Use when Codex needs to collect newly published papers from configured journals and subjournals, filter out non-biology content, classify papers into fixed categories, translate titles into Chinese, write concise Chinese summaries, export digest tables, or send the result by email on a daily schedule.
---

# Bio Literature Digest

## Overview

Build a daily paper-digest pipeline around a configurable journal watchlist. Favor official journal RSS, table-of-contents, or advance-online sources, normalize metadata, filter for biology relevance, classify into fixed categories, and produce a bilingual digest with English titles, Chinese titles, Chinese summaries, abstracts, DOI, journal, publish time, and links.

Default operating assumptions for this skill:
- Run on China Standard Time.
- Deliver the daily digest at 08:00 CST.
- Use the scheduled digest window: previous local calendar day `00:00` to `24:00` CST by default.
- Only use `previous_day_to_delivery` when the operator explicitly wants the legacy span from previous day `00:00` to delivery time.
- Include all article types unless the user narrows scope later.
- Prefer QQ Mail or 163 Mail SMTP for delivery.

Project layout is intentionally split by information type:
- `config/content/`: watchlist, rules, glossary, terminology sources
- `config/integrations/`: email, style, translation, external review providers
- `config/runtime/`: portable runtime baseline
- `assets/`: presentation templates
- `scripts/`: executable pipeline entrypoints
- `src/bio_literature_digest/`: reusable implementation modules
- `docs/`: operator-facing docs and artifact contract
- `ops/`: scheduler and deployment assets
- `local/`: machine-local config overrides and env files
- `var/`: work directories, archives, reviews, logs, and SQLite runtime state

Before modifying scripts, configs, docs, scheduler assets, or adding/removing files, read [engineering_harness.md](./docs/engineering_harness.md). Treat it as the mandatory placement and secrecy contract for this project. After changes, run `python3 scripts/check_project.py`. Use `python3 scripts/check_harness.py` and `python3 scripts/check_alignment.py` only when isolating a specific layer.

Load these config files before implementing or revising the pipeline:
- [journal_watchlist.yaml](./config/content/journal_watchlist.yaml) for the first-pass journal universe and source strategy.
- [category_rules.yaml](./config/content/category_rules.yaml) for fixed categories, relevance filters, and output requirements.
- [email_config.example.yaml](./config/integrations/email_config.example.yaml) for SMTP config shape.
- [translation_config.example.yaml](./config/integrations/translation_config.example.yaml) for HTTP-based translation providers such as Google-, Bing-, or Youdao-compatible gateways.
- [llm_review_config.example.yaml](./config/integrations/llm_review_config.example.yaml) for running LLM relevance review outside Codex through an HTTP or command adapter.
- [production.example.yaml](./config/runtime/production.example.yaml) for the portable runtime baseline (paths, timezone, delivery defaults, and sidecar shape).

Use `./local/runtime/production.yaml` as the machine-local override of `production.example.yaml`.

For isolated local development, create and use a skill-local virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 -m unittest discover -s tests
```

For cross-platform local execution, prefer the built-in wrapper:

```bash
python3 scripts/with_env.py -- python3 scripts/run_digest.py ...
```

`with_env.py` auto-detects the OS, loads `./local/.env.local`, and then runs the requested command in that environment. Use it instead of remembering separate `source` commands for macOS, Linux, or Windows.

All live secrets must exist only in `./local/.env.local`. Do not hardcode API keys, SMTP authorization codes, or other secret values in Python scripts, YAML config files, automation files, or test fixtures.

Run this audit before shipping or migrating the skill:

```bash
python3 scripts/audit_secrets.py
```

For scheduled or production delivery, do not call `run_digest.py` directly from an automation. Always use:

```bash
python3 scripts/run_production_digest.py
```

`run_production_digest.py` is the canonical production entrypoint. It loads `./local/.env.local`, uses the runtime-configured local email/style/translation configs, applies the scheduled digest window, and keeps manual runs aligned with scheduled runs.

Treat any web-app sync as an optional sidecar, not part of the producer critical path. The default production run should complete the digest, local exports, email, archive, review workspace sync, and backlog refresh even when the web importer is absent or unhealthy. Only enable web sync explicitly when the separate web deployment and its Python environment are known-good.

Optional database sync is configured in runtime YAML under `database.enabled` and `database.sqlite_path`. When enabled, `run_production_digest.py` will sync `digest.csv`, `review_queue.csv`, and `daily_review.csv` to SQLite via `scripts/sync_digest_db.py` after archive output is written.

The production entrypoint also archives the daily digest outputs. After each successful run it stores `digest.html`, `digest.csv`, `digest.xlsx`, `review_queue.csv`, `daily_review.csv`, and `daily_review.xlsx` in a date-stamped folder under `var/archives/daily-digests/`, syncs the editable review workspace at `var/reviews/daily-reviews/YYYY-MM-DD/`, updates the active review backlog at `var/reviews/backlog/review_backlog.xlsx`, and deletes archived folders older than 30 days. If `send_email` fails after the exports are already generated, still archive the run artifacts and review surfaces so the failed run remains debuggable and can be replayed manually. For human review, treat `review_backlog.xlsx` as the canonical editable file; `review_backlog.csv` and `review_backlog.html` are derived views, not the source of truth.

For the optimizer layer, do not use a standalone Python maintainer that rewrites rules on its own. Use Codex to read the producer artifacts, validate `run_metadata.json`, inspect `rule_feedback_report.md`, `classification_suggestions.json`, `glossary_candidates.yaml`, `review_queue.csv`, and the active review backlog `var/reviews/backlog/review_backlog.xlsx` plus `var/reviews/backlog/review_backlog_state.json`, then update `config/content/category_rules.yaml` and `config/content/bio_translation_glossary.yaml` conservatively with a human-readable change summary.

Use this sequence:
1. Run `python3 scripts/refresh_review_backlog.py` so the active backlog reflects any late human edits in `var/reviews/daily-reviews/YYYY-MM-DD/`. This refresh prefers `daily_review.xlsx` over `daily_review.csv`, and it must preserve any editable values already present in `var/reviews/backlog/review_backlog.xlsx`.
2. Read only backlog rows whose `review_status` is `reviewed_pending_optimization`.
3. Use the built-in admission tiers:
   - `apply`: low-risk human feedback that aligns with the current decision/category; Codex may use it directly for conservative rule or glossary updates.
   - `suggest`: human feedback that changes a decision or category; Codex must validate it against the paper content, existing rules, and other recent examples before updating rules.
   - `observe`: weak or interest-only feedback; do not update hard rules from it, but it may inform ranking or future pattern observation.
4. Update the rules/glossary conservatively.
5. Write a selective batch file such as `var/reviews/backlog/optimization_selection.json` that lists only the backlog rows Codex actually consumed into stable updates. Do not bulk-consume all reviewed rows, because deferred or ambiguous cases should remain in the backlog and continue accumulating evidence.
6. Run `python3 scripts/mark_review_backlog_optimized.py --selection-json var/reviews/backlog/optimization_selection.json` after the Codex optimization succeeds.
7. Run `python3 scripts/finalize_review_backlog.py` to archive only those consumed rows out of the active backlog, archive the consumed `optimization_selection.json`, clear it from the active backlog root, and rebuild the backlog views.

## Workflow

Follow this order unless the user explicitly requests a different design.

### 1. Build or update the source registry

Use `config/content/journal_watchlist.yaml` as the single source of truth for:
- journals to monitor
- whether each source is enabled
- source family and retrieval strategy
- topic expectations and exclusion hints

Do not hardcode journal lists in scripts if the same information belongs in the watchlist.

Prefer this retrieval order:
1. Official RSS or advance-online feeds from the publisher or journal.
2. Official table-of-contents pages when feeds are incomplete.
3. Crossref or publisher APIs as a fallback for metadata completion.

Preserve the ability to add or remove journals without code changes.

### 2. Fetch incremental records

Fetch only newly published or newly surfaced records for the target window. The default scheduled window is the previous local calendar day `00:00` to `24:00` CST. Use the lookback mode only for ad hoc debugging or backfills.

For each record, capture at minimum:
- journal
- publisher
- article type
- title
- DOI
- URL
- published timestamp
- abstract or summary text if available

Retain the raw fetched payload long enough to debug parsing problems. Discard it from the final report unless the user asks for archival storage.

### 3. Normalize and deduplicate

Normalize records into one consistent schema before filtering or classification.

Use this duplicate priority:
1. DOI exact match
2. Canonical article URL
3. Normalized title plus journal

Prefer the most complete record when duplicate candidates disagree. Keep the earliest publisher timestamp if multiple timestamps exist.

### 4. Filter for biology relevance

Apply two-stage filtering:

1. Source-aware filtering
   Keep only configured journals and subjournals.

2. Article-aware filtering
   Keep papers relevant to biology, plant biology, molecular biology, genetics, genomics, proteomics, bioinformatics, methods, databases, or AI-for-bio.

Exclude papers that are clearly outside scope, especially:
- pure ecology without mechanistic or molecular biology content
- pure materials science
- pure physics
- pure chemistry
- engineering papers with no meaningful biological question

Treat journals such as `Nature Machine Intelligence` and `Patterns` as conditional sources. Keep only papers with clear biology, biomedical, omics, protein, genetics, or bioinformatics relevance.

Use keyword rules first, then use an LLM pass to resolve borderline cases.

### 5. Classify into fixed categories

Assign each retained paper to exactly one fixed category from `config/content/category_rules.yaml`.

Prefer deterministic keyword or journal cues first. Use an LLM pass only to break ties or classify ambiguous items. If the paper still does not fit cleanly, assign `other`.

Keep the category set small and stable. Do not create ad hoc categories during routine runs.

### 6. Translate and summarize

Before translation, run a second-stage LLM review over the rule-kept set. The LLM should return:
- `keep`, `review`, or `reject`
- confidence
- short reason
- optional category override

Default behavior is to send `keep` records to translation and digest export, and export `review` records into a separate review queue for manual inspection.

For the current production digest, when the user has explicitly allowed review-pending delivery, append `review` items after the confirmed items and sort them last in the email body and attachments.

For every retained `keep` paper, generate:
- `title_en`: original English title
- `title_zh`: concise Chinese title
- `summary_zh`: concise Chinese summary for a wet-lab or computational biology reader

Also preserve:
- abstract
- DOI
- journal
- publish date
- article URL
- category
- tags

Write summaries to answer three questions:
- What was studied?
- What was found or built?
- Why does it matter for biology, plant science, or AI-for-bio?

Keep the summary factual. Do not invent results not supported by the title and abstract.

### 7. Export the digest

Produce at least:
- an HTML email body
- a CSV attachment
- an XLSX attachment

The table should contain these columns in this order unless the user changes it:
1. `journal`
2. `publish_date`
3. `category`
4. `interest_level`
5. `interest_tag`
6. `title_en`
7. `title_zh`
8. `summary_zh`
9. `abstract`
10. `doi`
11. `article_url`
12. `tags`

Group the email body by category. Keep the email body shorter than the attachments by truncating long abstracts or summaries if needed.
Render `interest_level` as stars in the email body and render `interest_tag` in smaller text near the title metadata.

### 8. Send by email

Use SMTP with per-provider settings from `config/integrations/email_config.example.yaml`.

Default delivery assumptions:
- provider is QQ Mail or 163 Mail
- authentication uses an app password or SMTP authorization code, not the login password
- schedule is daily at 08:00 CST

If email sending fails, still export the digest files locally and report the failure reason.

## Implementation Notes

Keep the pipeline modular. A typical script split is:
- `fetch_feeds.py`
- `normalize_and_dedupe.py`
- `filter_bio_relevance.py`
- `classify_papers.py`
- `llm_review.py`
- `translate_and_summarize.py`
- `export_digest.py`
- `optimization_reports.py` (`rule-feedback`, `classification-suggestions`, `glossary-candidates`)
- `send_email.py`
- `run_digest.py`

Compatibility wrappers (`rule_feedback_report.py`, `classification_suggestions.py`, `build_glossary_candidates.py`) are intentionally kept for external callers and gradual migration.

Use configuration files for journal scope, filtering, and SMTP settings. Avoid encoding editorial logic directly in the mailer or fetch scripts.

The current script bundle requires Python + `PyYAML`. `translate_and_summarize.py` ships with:
- `placeholder` mode for offline validation
- `command` mode for plugging in an external LLM or translation command without changing the rest of the pipeline
- `http-json` mode for plugging in a JSON-speaking translation service through configuration
- `google-basic-v2` mode for Google Cloud Translation Basic v2 with an API key
- `tencent-tmt` mode for Tencent Cloud TextTranslate, typically used as fallback

`llm_review.py` follows the same pattern. Use it to add a second-stage relevance decision after rules and before translation/emailing. The recommended production flow is:
- rules for high-recall prefiltering
- LLM review for `keep/review/reject`
- human review only for the `review` queue
- periodic rule updates from `rule_feedback_report.md`

If the user wants to stay entirely inside the Codex environment and not configure any external model service, use:
- `--review-provider placeholder` to create a conservative `review_queue.csv`
- let Codex or the user edit `var/reviews/backlog/review_backlog.xlsx` by filling `interest_level`, `interest_tag`, `review_final_decision`, `review_final_category`, and `reviewer_notes`
- if a one-off replay is needed, export the reviewed rows to CSV and rerun with `--manual-review-csv /path/to/manual_review.csv`

Do not send email automatically while `review_queue` is non-empty unless the user explicitly opts in.

For a full dry run with pre-fetched JSONL input, use:

```bash
python3 scripts/run_digest.py \
  --work-dir /path/to/bio-digest-run \
  --input-file /path/to/raw_records.jsonl \
  --skip-email \
  --summary-provider placeholder
```

For a production-style run with model review outside Codex, add:

```bash
python3 scripts/run_digest.py \
  --work-dir /path/to/bio-digest-run \
  --review-provider http-json \
  --review-config config/integrations/llm_review_config.example.yaml \
  --summary-provider http-json \
  --summary-config config/integrations/translation_config.example.yaml
```

For Google-first translation with Tencent fallback, use:

```bash
python3 scripts/run_digest.py \
  --work-dir /path/to/bio-digest-run \
  --review-provider placeholder \
  --summary-provider google-basic-v2 \
  --summary-config local/integrations/translation_google_basic_v2.yaml
```

Each successful run can also emit:
- `glossary_candidates.yaml`
- `glossary_candidates.md`
- `classification_suggestions.json`
- `classification_suggestions.md`
- `daily_review.csv`
- `daily_review.xlsx`

Use those artifacts to review and append new biology terms into `config/content/bio_translation_glossary.yaml` during daily Codex maintenance. If the user wants scheduled optimization, schedule Codex itself to:
1. optimize rules, sources, and terminology from the latest successful run
2. inspect whether `var/reviews/backlog/review_backlog.xlsx` contains newly reviewed rows after refresh
3. if it changed, learn from `interest_level`, `interest_tag`, `review_final_decision`, `review_final_category`, and `reviewer_notes`
4. update rule, classification, interest, and tag heuristics conservatively
5. mark only the rows that were actually consumed into stable decisions; leave deferred rows in the backlog
Use [terminology_sources.yaml](./config/content/terminology_sources.yaml) as the official-source shortlist when the user wants downloadable biology vocabularies or ontology resources.

For a Codex-only review loop without external LLM services:

```bash
python3 scripts/run_digest.py \
  --work-dir /path/to/bio-digest-run \
  --input-file /path/to/raw_records.jsonl \
  --skip-email \
  --review-provider placeholder \
  --summary-provider placeholder
```

Then edit `/path/to/bio-digest-run/daily_review.xlsx` or merge your changes into `var/reviews/backlog/review_backlog.xlsx`, export a manual-review CSV if needed, and rerun:

```bash
python3 scripts/run_digest.py \
  --work-dir /path/to/bio-digest-run \
  --input-file /path/to/raw_records.jsonl \
  --skip-email \
  --review-provider placeholder \
  --manual-review-csv /path/to/bio-digest-run/manual_review.csv \
  --summary-provider placeholder
```

When building the pipeline, favor deterministic fallbacks:
- If abstract parsing fails, keep the record and mark `abstract` as missing.
- If classification is uncertain, use `other`.
- If translation or summary generation fails, keep the English title and leave a retriable placeholder.

## Validation

When validating this skill or its scripts:
- test with a small subset of journals first
- verify that unrelated material-science or chemistry papers are filtered out
- verify that AI journals keep only biology-relevant papers
- verify that duplicate DOI entries collapse to one record
- verify that the exported table contains bilingual titles and Chinese summaries
- verify that email delivery works with the chosen SMTP provider

If the user asks for a proposal rather than implementation, update the references first and leave scripts unimplemented.
