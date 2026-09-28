# Multi-worker daily radar protocol

This repository uses a staged ChatGPT pipeline so "0 ideas" is only possible after complete end-to-end coverage.

Daily run root:
`state/runs/YYYY-MM-DD/` using Europe/Istanbul date.

Stages:
1. discovery workers 1-4
2. merge/candidate builder
3. validators A-B
4. finalizer/publication

Files:
- `discovery/worker-1.json`
- `discovery/worker-2.json`
- `discovery/worker-3.json`
- `discovery/worker-4.json`
- `merge/status.json`
- `merge/candidates.json`
- `validation/validator-a.json`
- `validation/validator-b.json`
- `final/report.json`

The finalizer MUST NOT update `state/idea_history.json` or `state/idea_catalog.json`
unless every required upstream stage reports complete coverage.

A valid zero-new-idea result therefore requires:
- 4/4 discovery workers complete
- all feed items triaged exactly once
- merge complete
- every candidate assigned to one validator
- both validators complete
- every candidate validated
- cross-day semantic dedup complete

The rolling news window remains 72 hours. Idea history remains persistent.
