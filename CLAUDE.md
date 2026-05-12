# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`README.md` is the user-facing reference (CSV schema, API routing details, dashboard publishing setup, known limitations). Read it before designing changes that touch the data contract.

## Pipeline

Three scripts run in strict order; each consumes the previous one's output:

```
nanda_usage_scraper.py   →  data/nanda_usage_stats_{latest,YYYY-MM-DD}.csv
                            data/nanda_usage_timeseries_{latest,YYYY-MM-DD}.csv
generate_delta.py        →  data/delta_{latest,YYYY-MM-DD}.md
build_dashboard.py       →  docs/index.html
```

`generate_delta.py` and `build_dashboard.py` both find the prior snapshot with the same regex (`nanda_usage_stats_YYYY-MM-DD.csv`, second-newest). Anything that doesn't match — `*_latest.csv`, `*_revised.csv`, manual exports — is ignored on purpose. Don't break that pattern.

GitHub Actions (`.github/workflows/monthly-scrape.yml`) runs the three scripts on the 1st of every month at 09:00 UTC and commits results back to `main`. Manual local runs follow the same order.

## Inventory is the source of truth

`inventory.csv` (columns: `study_id, archive, deposit_via, status, title, version, version_date, doi, url`) drives two things the scraper does not hardcode:

- **Study list** — `nanda_usage_scraper.STUDY_IDS` is derived from the file at import time.
- **API routing** — `archive` ∈ {`ICPSR`, `openICPSR`} picks the endpoint set per study. `ICPSR` uses PCMS `/downloadCount` + `/downloadInfo` + `/institution` + the publications search API (full breakdown). `openICPSR` uses the openICPSR usage view (totals only, no per-month time-series).

To add a dataset, append a row — never edit the scraper's study list. The `add_to_inventory.py` helper (wrapped by `add_to_inventory.ps1`) fetches metadata from DataCite (primary) → JSON-LD scrape (fallback), validates strictly, and appends. The `.ps1` wrapper also handles the git commit/pull-rebase/push, and prompts before any git activity. Hand-editing `inventory.csv` is still fine for cases the validator rejects.

`deposit_via=RDE` rows return zero usage from the openICPSR endpoint (known issue, see README "Limitations") — don't treat zero as a bug for those rows.

## Cloudflare

`pcms.icpsr.umich.edu` is behind Cloudflare. The scraper and `add_to_inventory.py` both use `cloudscraper`, not `requests`, for that host. GitHub Actions occasionally trips the challenge and the monthly job fails — fall back to running locally and committing manually.

## Commands

```powershell
# Run the full pipeline (mirrors what CI does)
pip install -r requirements.txt
python nanda_usage_scraper.py     # ~3 min for ~100 studies, polite 1s delay between calls
python generate_delta.py
python build_dashboard.py

# Add a newly published dataset (preferred path — commits and pushes)
.\add_to_inventory.ps1 <study_id> -Archive <ICPSR|openICPSR> [-DepositVia RDE] [-DryRun] [-Force]

# Run the Python helper without git steps
python add_to_inventory.py <study_id> --archive {ICPSR|openICPSR} [--deposit-via {legacy|RDE}] [--dry-run] [--force]

# Tests (pytest; only add_to_inventory is covered today)
pytest tests/
pytest tests/test_add_to_inventory.py::test_happy_path_icpsr_appends_row    # single test
```

The tests mock `fetch_datacite` / `fetch_json_ld` and use a tmp-copy of `inventory.csv`. Study IDs `999900`, `999001`, `888777` are reserved for tests — don't add them to the real inventory.

## Editing notes

- **`docs/index.html` is generated.** Edit `build_dashboard.py` (and `docs/assets/nanda-logo.svg` for the wordmark); never hand-edit `docs/index.html` — the next scrape overwrites it.
- **`debug/` and `TASKS.md` are gitignored.** Local-only — diagnostic probe scripts and project task list. Don't try to commit them.
- **GitHub Pages publishes from `/docs`** — that's why the dashboard file lives there. Pages doesn't allow arbitrary subfolders.
- **DOI version stripping.** `nanda_usage_scraper.strip_doi_version` drops `.vN` / `VN` suffixes before writing rows, because DataCite only mints DOIs at major-version granularity. Don't reintroduce versioned DOIs in scraper output.
- **Title prefix stripping.** `load_inventory` strips `"National Neighborhood Data Archive (NaNDA): "` from titles at load. Downstream consumers (dashboard, delta report) see the short form.
- **Date window.** Scraper sends `startDt=01/01/2020, endDt=today` — lifetime totals since NaNDA's first ICPSR release. PCMS's public utilization page defaults to last 3 years, so our totals will exceed the page's headline. Not a bug.
