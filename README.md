# Lovable Opportunity Radar — Combined RSS

This repository turns the **105-source OPML** into one combined feed that ChatGPT can read.

## What it creates

After each GitHub Actions run:

- `docs/feed.xml` — combined RSS 2.0 feed
- `docs/latest.json` — richer machine-readable version for ChatGPT
- `docs/status.json` — source-by-source health report
- `docs/batches/` — deterministic 40-item analysis batches
- `state/idea_history.json` — persistent semantic history of ideas already reported
- `state/current_run/` — per-run raw opportunity ledgers, merged candidates and final state

The workflow runs **hourly** and retains a rolling **72-hour** news window. The ChatGPT radar analyzes the full current 72-hour dataset in deterministic 40-item batches.

## Important source note

The supplied OPML currently uses **Google News domain-restricted RSS queries** for the 105 source websites. This makes the whole set importable without Inoreader Pro, but it is not identical to native RSS coverage.

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
- `MAX_PER_SOURCE=30`
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
