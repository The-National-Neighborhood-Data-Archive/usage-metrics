# NaNDA Usage Metrics

The National Neighborhood Data Archive (NaNDA) publishes contextual data on US neighborhoods — pollution, parks, schools, transit, demographics, and more. This repository tracks who's actually using each dataset: monthly download counts, related publications, unique institutions, and historical trends, pulled from ICPSR and openICPSR.

**Live dashboard:** [the-national-neighborhood-data-archive.github.io/usage-metrics](https://the-national-neighborhood-data-archive.github.io/usage-metrics/)

## What's in this repo

A Python scraper (`nanda_usage_scraper.py`) runs monthly via GitHub Actions, hitting ICPSR's PCMS APIs for every dataset listed in `inventory.csv`. It produces a monthly snapshot CSV, a long-format time-series CSV going back to 2020, a Markdown delta report comparing the latest run to the previous one, and a self-contained HTML dashboard. `inventory.csv` is the single source of truth for what gets tracked — append a row there to add a dataset.

## Outputs

All under `data/` unless noted:

- **Monthly snapshot** — `nanda_usage_stats_YYYY-MM-DD.csv` (dated) and `nanda_usage_stats_latest.csv` (always overwritten). One row per dataset.
- **Time-series** — `nanda_usage_timeseries_*.csv`. Long-format monthly buckets per curated dataset, going back to 2020.
- **Delta report** — `delta_*.md`. Plain-English summary of what changed since the last snapshot: total downloads, biggest movers, suspicious zeros, newly tracked datasets.
- **Dashboard** — `docs/index.html`. KPI cards, an aggregate monthly downloads chart, and a sortable table of every dataset. Published via GitHub Pages.

## CSV schema

### Monthly snapshot (`nanda_usage_stats_*.csv`)

| Column | Description |
|--------|-------------|
| `study_id` | ICPSR or openICPSR study/project ID |
| `dataset_title` | Full dataset title (joined from `inventory.csv` by `study_id`) |
| `doi` | Dataset DOI (joined from `inventory.csv` by `study_id`) |
| `url` | Landing-page URL (joined from `inventory.csv` by `study_id`) |
| `total_downloads` | Total downloads (data + docs for curated; total downloads for openICPSR) |
| `total_views` | Total project-page views (openICPSR only; blank for curated) |
| `publications` | Count of related publications (curated ICPSR only; blank for openICPSR) |
| `data_downloads` | Data file downloads (curated only; blank for openICPSR) |
| `documentation_downloads` | Documentation file downloads (curated only; blank for openICPSR) |
| `unique_users` | Distinct users who downloaded (curated only; blank for openICPSR) |
| `num_institutions` | Distinct institutions that downloaded (curated only; blank for openICPSR) |
| `status` | `success` or `error` |
| `error_message` | Populated when `status == error`, or for non-fatal sub-fetch failures (e.g., publications fetch error, unknown archive value) |
| `timestamp` | When this row was scraped |

### Time-series (`nanda_usage_timeseries_*.csv`)

Long-format with one row per `(study_id, year, month)`. Months with zero activity are omitted. Curated ICPSR datasets only — PCMS doesn't expose a per-month feed for openICPSR.

| Column | Description |
|--------|-------------|
| `study_id` | ICPSR study ID (curated only) |
| `year` | Year of activity (e.g., 2024) |
| `month` | Month 1–12 |
| `data_downloads` | Data file downloads that month |
| `documentation_downloads` | Documentation downloads that month |
| `total_downloads` | Sum of the two |
| `timestamp` | When this snapshot was scraped (same value for every row in a run) |

## How it works

Routing is two-tiered: `deposit_via=RDE` wins first (the only place RDE numbers exist), then `archive` picks the legacy endpoint set.

- **`deposit_via=RDE`** (any archive): `www.icpsr.umich.edu/sites/api/usage-statistics-api/usage-statistics/products/{id}` — GA4-backed lifetime totals plus a data/documentation download split. No views, no publications, no time-series. Powers the new `/sites/nanda/view/studies/{id}` pages.
- **`archive=ICPSR`** + legacy (curated): `pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadCount`, `/downloadInfo`, `/institution` — full breakdown of data vs. documentation downloads, unique users, and institutions.
- **`archive=openICPSR`** + legacy: `pcms.icpsr.umich.edu/pcms/metrics/data/api/openicpsr/projects/{id}/usage/view?level=project` — total downloads, total views, and a publications count.
- **Publications** (curated only): `search.icpsr.umich.edu/.../publications?STUDYQ={id}` — Solr search API; we read `response.numFound` for the count.

Dataset titles are read from `inventory.csv` at startup, not fetched live. `cloudscraper` handles `pcms.icpsr.umich.edu`'s Cloudflare challenge.

## Maintaining the inventory

`inventory.csv` is the single file to edit when datasets are added or removed. Each row carries `study_id`, `archive` (`ICPSR` or `openICPSR`), `deposit_via` (`legacy` or `RDE`), `status` (`published` or `unpublished`), `title`, `version`, `version_date`, `doi`, and `url`. The scraper derives the list of studies to scrape from `study_id` at runtime, joins titles by ID, and routes API calls by `archive`.

To add a newly-published dataset, use the `add_to_inventory.ps1` PowerShell wrapper. It runs the metadata fetch, the CSV append, and the git commit + push in one shot:

```powershell
cd usage-metrics
.\add_to_inventory.ps1 <study_id> -Archive <ICPSR|openICPSR>
```

Optional flags: `-DepositVia legacy` (default `RDE` — every new deposit goes through the RDE pathway; use `legacy` only for backfilling pre-RDE rows), `-DryRun` (preview only, no write, no commit), `-Force` (overwrite an existing row for the same `study_id` — useful for typo fixes). The wrapper prompts before committing so you can eyeball the row first, and runs `git pull --rebase origin main` before pushing in case the monthly scrape committed ahead of you. Run `Get-Help .\add_to_inventory.ps1 -Examples` to see usage examples.

Under the hood, the wrapper calls `add_to_inventory.py`, which fetches title, version, version_date, and DOI from DataCite (with a fallback to the public ICPSR page) and validates the result. To run the Python helper directly without the git steps, call it the same way:

```bash
python add_to_inventory.py <study_id> --archive {ICPSR|openICPSR} [--deposit-via {legacy|RDE}] [--dry-run] [--force]
# --deposit-via defaults to RDE; pass --deposit-via legacy only for pre-RDE backfills
```

Hand-editing `inventory.csv` still works for edge cases the validator rejects.

## Running locally

GitHub Actions runs the full pipeline (scraper + delta report + dashboard build) on the 1st of every month at 9 AM UTC and commits results back to the repo (`.github/workflows/monthly-scrape.yml`). Manual runs happen from the **Actions** tab.

To run locally:

```bash
cd usage-metrics
pip install -r requirements.txt
python nanda_usage_scraper.py     # ~3 min for 104 studies (1-second polite delay)
python generate_delta.py          # writes data/delta_*.md
python build_dashboard.py         # writes docs/index.html
```

To publish the dashboard, enable GitHub Pages: **Settings → Pages → Source: Deploy from a branch → Branch: `main` / folder: `/docs`**. Pages only allows publishing from `/` or `/docs`, which is why the file lives in `docs/`.

## Limitations

- **No per-institution download counts.** PCMS's `/institution` endpoint returns institution metadata (name, location, type) but no download counts per institution. We expose `num_institutions` but not a top-institutions list.
- **openICPSR has no documentation/data split.** The openICPSR usage endpoint returns one `totalDownloads` figure with no breakdown.
- **No geographic breakdown.** PCMS does not expose a country/region/state download breakdown for studies. Verified by probing every plausible endpoint and inspecting the dashboard JS bundles; no such widget exists in the public utilization page.
- **RDE totals are GA4-only and not comparable across routes.** Numbers for `deposit_via=RDE` rows come from the NaNDA tenant's GA4-backed usage-statistics endpoint, which only captures activity since GA4 tracking went live on the new tenant. A study that lived in curated PCMS first will look much smaller on the RDE endpoint — e.g., curated 38528 shows ~thousands of lifetime downloads in PCMS but only 105 on the GA4 endpoint. Don't compare an RDE row's total to a curated row's total without that caveat. The GA4 endpoint also returns 500 for very new studies until ingestion catches up (status logged in `error_message`, counts stay at 0).
- **RDE rows have no per-month time-series, views, publications, or institutions.** The NaNDA usage-statistics endpoint exposes only lifetime totals plus the data/documentation split, so RDE rows are excluded from `nanda_usage_timeseries_*.csv` and leave `total_views`, `publications`, `unique_users`, and `num_institutions` blank.

## Notes

**Date window — read before comparing to the PCMS page.** The scraper passes `startDt=01/01/2020, endDt=today` to PCMS — lifetime since NaNDA's first ICPSR release. The public utilization page at `pcms.icpsr.umich.edu/pcms/metrics/studies/{id}/utilization` defaults to the last 3 years, so our `total_downloads` will run higher than the page's headline number by exactly the count of pre-(today − 3 years) activity. To reconcile manually, set the page's Start Date to `01/01/2020` and click **Go**.

**Cloudflare on GHA.** GitHub Actions sometimes runs from IP ranges Cloudflare treats as bot traffic. If a monthly run fails with a Cloudflare challenge, fall back to running `python nanda_usage_scraper.py` locally and committing the results manually.

**Diagnostic scripts.** Probe scripts in `debug/` (kept local, not pushed) help locate new endpoints if ICPSR changes its page structure or API.
