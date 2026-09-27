# Radar persistent state

This folder is used by the ChatGPT scheduled radar as persistent state.

- `idea_history.json` — compact semantic history of ideas already reported to the user. It is intentionally NOT limited by the 72-hour news window.
- `current_run/manifest.json` — progress/status of the latest analysis run.
- `current_run/raw-batch-XXX.json` — raw opportunity ledger written after each processed news batch.
- `current_run/candidates.json` — merged/deduplicated candidates before final competitor verification.
- `current_run/final.json` — new ideas, suppressed duplicates, materially updated old ideas, and unverified candidates from the latest run.

## Cross-day deduplication

Ideas are matched semantically using a canonical key based on:

`target customer + core job + product mechanism`

Product name, article headline, publication date, price estimate, and competitor count do NOT by themselves create a new idea.

A previously reported idea is not emitted again as a new idea. New supporting news updates its history. Only a material change may appear in the separate "existing idea update" section.
