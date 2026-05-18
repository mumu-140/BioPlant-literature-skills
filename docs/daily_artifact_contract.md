# Daily Artifact Contract

This skill is split into two layers:

- Producer layer: fetches papers, applies rules and AI providers, exports artifacts, and optionally sends email.
- Optimizer layer: Codex or another AI tool reads the exported artifacts and decides whether the run succeeded, needs review, or needs rule/prompt/source changes.

The producer implementation may change across machines or platforms. The artifact contract must stay stable.

## Target Window

For scheduled production runs, the canonical window is:

- previous local calendar day `00:00` to `24:00` in `Asia/Shanghai`

Legacy compatibility remains available through runtime YAML:

- `delivery.window_policy: previous_day_to_delivery`

But the default contract should use:

- `delivery.window_policy: previous_day`

The resolved UTC window must be written into `run_metadata.json`.

## Core Artifacts

Every producer should write these files into its run directory:

- `digest.html`
- `digest.csv`
- `digest.xlsx`
- `review_queue.html`
- `review_queue.csv`
- `review_queue.xlsx`
- `daily_review.csv`
- `daily_review.xlsx`
- `run_metadata.json`

These are the minimum contract files that Codex and other AI tools may rely on.

## Optional Supporting Artifacts

These files are recommended for debugging and optimization:

- `raw_records.jsonl`
- `normalized_records.jsonl`
- `final_review_queue.jsonl`
- `daily_review.html`
- `rule_feedback_report.md`
- `classification_suggestions.md`
- `classification_suggestions.json`
- `glossary_candidates.md`

The producer should also sync an editable review workspace outside the volatile run directory:

- `var/reviews/daily-reviews/YYYY-MM-DD/daily_review.xlsx`
- `var/reviews/backlog/review_backlog.xlsx`

The canonical human-editable review surface is `var/reviews/backlog/review_backlog.xlsx`. Daily review files are date-stamped snapshots that feed the backlog and remain useful for audit and replay.
Rows should leave the active backlog only after Codex explicitly selects them as consumed for stable optimization. Deferred or ambiguous rows should remain in the active backlog so evidence can accumulate across multiple review cycles.
Archived consumed rows should also suppress future backlog refreshes for the same record keys, so daily snapshot replay does not rehydrate already-consumed examples into the active backlog.

## Metadata Contract

`run_metadata.json` should include at least:

- contract name and version
- run `status`: `running`, `success`, or `failed`
- `started_at_utc`
- `finished_at_utc`
- `current_step`
- `completed_steps`
- `failed_step` when applicable
- `failure_type` and `failure_message` when applicable
- resolved UTC window
- producer config summary
- row counts for key JSONL and CSV outputs
- existence and size of core artifacts

## Validation Rules

Codex or another optimizer should validate:

- all core artifacts exist
- `run_metadata.json` reports `success`
- CSV row counts match metadata counts
- `digest.csv` is not unexpectedly empty
- missing or empty outputs are flagged
- failures identify the exact failed step
- `daily_review.xlsx` exists and contains editable `interest_level` and `interest_tag` columns
- `var/reviews/backlog/review_backlog.xlsx` exists as the canonical human-editable backlog
- if the editable backlog changed after refresh, use reviewed backlog rows as higher-priority supervision for later optimization

## Portability Rule

Portability is defined by the artifact contract, not by the scheduler.

- Mac may use `launchd`
- Windows may use Task Scheduler
- Codex may run post-checks
- another AI tool may do rule optimization

As long as the producer emits the same contract, the optimizer layer should not need platform-specific logic.
