# Lovable Opportunity Radar — Combined RSS

This repository turns the **155-source OPML** into one combined feed that ChatGPT can read.

## What it creates

After each GitHub Actions run:

- `docs/feed.xml` — combined RSS 2.0 feed
- `docs/latest.json` — richer machine-readable version for ChatGPT
- `docs/status.json` — source-by-source health report
- `docs/batches/` — 40-item analysis batches for ChatGPT
- `docs/batches/` — deterministic 40-item analysis batches
- `state/idea_history.json` — persistent semantic history of ideas already reported
- `state/current_run/` — per-run raw opportunity ledgers, merged candidates and final state

The workflow runs **hourly** and retains a rolling **72-hour** news window. The ChatGPT radar analyzes the full current 72-hour dataset in deterministic 40-item batches.

## Important source note

The supplied OPML currently uses **Google News domain-restricted RSS queries** for the 155 source websites. This makes the whole set importable without Inoreader Pro, but it is not identical to native RSS coverage.

You can later replace any `xmlUrl` in `sources.opml` with a site's native RSS/Atom URL. The merger script needs no other change.

## Setup — about 5 minutes

1. Create a new **public GitHub repository**, for example:
   `lovable-opportunity-radar`

2. Extract this ZIP and upload **all files and folders** to the root of that repository.
   Make sure `.github/workflows/update-feed.yml` is preserved.

3. Open the repository's **Actions** tab.
   If GitHub asks, enable workflows.

4. Select **Update combined RSS** → **Run workflow** once.

5. When the run finishes, the repository will contain populated files under `docs/`.

## URLs to give ChatGPT

Replace `YOUR_USERNAME` and `YOUR_REPOSITORY`:

### Recommended: JSON
`https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPOSITORY/main/docs/latest.json`

### RSS
`https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPOSITORY/main/docs/feed.xml`

### Health/status
`https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPOSITORY/main/docs/status.json`

`latest.json` is recommended because it keeps source name, folder, source URL, publication time, first-seen time and summary in explicit fields.

## ChatGPT usage

Paste the JSON URL into ChatGPT together with the contents of `CHATGPT_RADAR_PROMPT.txt`.

For the recurring 07:00 radar, ChatGPT reads the master prompt, processes every batch in the current 72-hour window, and uses persistent GitHub state to avoid repeating ideas already reported on previous days.

## Manual refresh

GitHub → Actions → **Update combined RSS** → **Run workflow**.

## How often does it refresh?

The Action is scheduled hourly at minute 10 UTC. GitHub does not guarantee exact cron execution time and may delay scheduled jobs. Hourly refresh makes that irrelevant for a once-daily 07:00 analysis.

## Configuration

In `.github/workflows/update-feed.yml`:

- `RETENTION_HOURS=72`
- `MAX_ITEMS=1000`
- `MAX_PER_SOURCE=40`
- `FETCH_WORKERS=20`
- `FETCH_TIMEOUT=20`

## Source failures

A few source failures do not stop the workflow. `docs/status.json` records success/failure for every feed. The workflow fails only if **all** feeds fail.

## Repository structure

```text
.
├── .github/
│   └── workflows/
│       └── update-feed.yml
├── docs/
│   ├── feed.xml
│   ├── latest.json
│   ├── status.json
│   └── batches/
├── state/
│   ├── idea_history.json
│   └── current_run/
├── aggregate.py
├── sources.opml
├── requirements.txt
├── CHATGPT_RADAR_PROMPT.txt
└── README.md
```

## Türkiye sources

The source registry now contains **155 sources total**, including **50 Türkiye sources** across startups/technology, industry, retail, logistics, energy, public regulation and local Trakya/Lüleburgaz institutions.

A one-time Türkiye-only snapshot is stored under `docs/turkey-only/`. Normal hourly refreshes use all 155 sources together.

## Daily multi-worker analysis — 5 active tasks

Production uses exactly **5 ChatGPT scheduled tasks**:

```text
07:00  Discovery W1 → batches 01-06
07:00  Discovery W2 → batches 07-12
07:00  Discovery W3 → batches 13-18
07:00  Discovery W4 → batches 19-end

08:15, 09:15, ... 16:15
       Radar Orchestrator
       → discovery coverage gate/repair
       → merge + semantic dedupe
       → validation in max-5-candidate chunks
       → final publication after hard completion gate
```

The four discovery workers capture the same `source_batch_index_generated_at`
at the start. Later hourly collector refreshes therefore cannot silently change
the denominator during the same day's analysis.

The orchestrator performs **exactly one unfinished stage per invocation** and
persists progress under:

`state/runs/YYYY-MM-DD/`

Typical sequence:

```text
08:15 discovery gate
09:15 merge
10:15 validate candidates 1-5
11:15 validate candidates 6-10
12:15 validate candidates 11-15
13:15 finalize
```

If there are more candidates, later orchestrator runs continue with the next
validation chunk. If the run is already complete, later invocations do nothing.

The finalizer/publication logic is part of the orchestrator. It updates
`state/idea_history.json` and `state/idea_catalog.json` only when every hard
coverage gate passes.

A valid zero-new-idea result requires:
- all four discovery workers complete,
- every frozen feed record triaged exactly once,
- merge complete,
- every candidate competition-validated,
- semantic cross-day dedup complete.

The reporting metrics are intentionally separate:
- feed records triaged,
- original articles actually verified,
- raw opportunities generated,
- candidates competition-validated,
- final new ideas.

Therefore `1000/1000 feed records` never means that 1,000 full articles were opened.
