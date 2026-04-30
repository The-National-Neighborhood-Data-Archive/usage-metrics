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
| `total_downloads` | Total downloads (data + docs for curated; total downloads for openICPSR) |
| `total_views` | Total project-page views (openICPSR only; blank for curated) |
| `publications` | Count of related publications (curated ICPSR only; blank for openICPSR) |
| `data_downloads` | Data file downloads (curated only; blank for openICPSR) |
| `documentation_downloads` | Documentation file downloads (curated only; blank for openICPSR) |
| `unique_users` | Distinct users who downloaded (curated only) |
| `num_institutions` | Distinct institutions that downloaded (curated only) |
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

The scraper calls ICPSR's PCMS APIs directly. Routing comes from `inventory.csv`'s `archive` column:

- **`archive=ICPSR`** (curated): `pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadCount`, `/downloadInfo`, `/institution` — full breakdown of data vs. documentation downloads, unique users, and institutions.
- **`archive=openICPSR`**: `pcms.icpsr.umich.edu/pcms/metrics/data/api/openicpsr/projects/{id}/usage/view?level=project` — total downloads and total views.
- **Publications** (curated only): `search.icpsr.umich.edu/.../publications?STUDYQ={id}` — Solr search API; we read `response.numFound` for the count.

Dataset titles are read from `inventory.csv` at startup, not fetched live. `cloudscraper` handles `pcms.icpsr.umich.edu`'s Cloudflare challenge.

## Maintaining the inventory

`inventory.csv` is the single file to edit when datasets are added or removed. Each row carries `study_id`, `archive` (`ICPSR` or `openICPSR`), `deposit_via` (`legacy` or `RDE`), `status` (`published` or `unpublished`), `title`, `version`, `version_date`, `doi`, and `url`. The scraper derives the list of studies to scrape from `study_id` at runtime, joins titles by ID, and routes API calls by `archive`. To add a dataset, append a row, commit, and push — the next monthly run picks it up automatically.

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
- **RDE-deposited datasets return zero usage.** Studies with `deposit_via=RDE` in the inventory (currently 5 rows: 200038, 301419, 302178, 302343, 302937) live in openICPSR but consistently return zero downloads/views from the openICPSR endpoint. Cause unconfirmed — could be too new, or RDE deposits may not yet feed the same metrics pipeline. Future probing target.

## Notes

**Date window — read before comparing to the PCMS page.** The scraper passes `startDt=01/01/2020, endDt=today` to PCMS — lifetime since NaNDA's first ICPSR release. The public utilization page at `pcms.icpsr.umich.edu/pcms/metrics/studies/{id}/utilization` defaults to the last 3 years, so our `total_downloads` will run higher than the page's headline number by exactly the count of pre-(today − 3 years) activity. To reconcile manually, set the page's Start Date to `01/01/2020` and click **Go**.

**Cloudflare on GHA.** GitHub Actions sometimes runs from IP ranges Cloudflare treats as bot traffic. If a monthly run fails with a Cloudflare challenge, fall back to running `python nanda_usage_scraper.py` locally and committing the results manually.

**Diagnostic scripts.** Probe scripts in `debug/` (kept local, not pushed) help locate new endpoints if ICPSR changes its page structure or API.
