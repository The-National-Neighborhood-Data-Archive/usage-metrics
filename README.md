# NaNDA Usage Metrics Scraper

Automated monthly scraper that pulls download counts (and related stats) for every NaNDA dataset hosted on ICPSR and openICPSR. Output is a CSV in `data/`.

## How it works

`nanda_usage_scraper.py` calls the ICPSR PCMS APIs directly — no browser, no HTML parsing. It uses two endpoints depending on study type:

- **Curated ICPSR studies** (5-digit IDs): `pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadCount`, `/downloadInfo`, `/institution`. Returns the full breakdown: data vs. documentation downloads, unique users, and unique institutions.
- **openICPSR projects** (6-digit IDs): `pcms.icpsr.umich.edu/pcms/metrics/data/api/openicpsr/projects/{id}/usage/view?level=project`. Returns total downloads and total views.
- **Publications search API** (curated only): `search.icpsr.umich.edu/search/api/1.0/default/search/applications/icpsr/modules/icpsr/publications?STUDYQ={id}`. Returns a Solr-style response; we read `response.numFound` for the count.

`cloudscraper` is used because `pcms.icpsr.umich.edu` sits behind Cloudflare and plain `requests` gets challenged.

## Date window — read before comparing to the PCMS page

The scraper passes `startDt=01/01/2020, endDt=today` to PCMS — **lifetime since NaNDA's first ICPSR release**.

The public PCMS utilization page at `pcms.icpsr.umich.edu/pcms/metrics/studies/{id}/utilization` defaults to **the last 3 years**. So our `total_downloads` will routinely run higher than the page's headline number — by exactly the count of pre-(today − 3 years) activity. That's expected, not a bug.

To reconcile manually, set the page's Start Date to `01/01/2020` and End Date to today, then click **Go**. The page numbers will then match what the scraper records.

## Schedule

GitHub Actions runs `nanda_usage_scraper.py` automatically on the 1st of every month at 9 AM UTC, then commits the new CSV back to the repo. The workflow lives at `.github/workflows/monthly-scrape.yml`. You can also trigger a manual run from the **Actions** tab.

## Output

All files in `data/`:

- `nanda_usage_stats_YYYY-MM-DD.csv` — dated snapshot from each run
- `nanda_usage_stats_latest.csv` — always overwritten with the most recent run

### CSV columns

| Column | Description |
|--------|-------------|
| `study_id` | ICPSR or openICPSR study/project ID |
| `dataset_title` | Full dataset title (parsed from the JSON-LD `name` field on the DOI page) |
| `total_downloads` | Total downloads (data + docs for curated; total downloads for openICPSR) |
| `total_views` | Total project-page views (openICPSR only; blank for curated) |
| `publications` | Count of related publications (curated ICPSR only; blank for openICPSR) |
| `data_downloads` | Data file downloads (curated only; blank for openICPSR) |
| `documentation_downloads` | Documentation file downloads (curated only; blank for openICPSR) |
| `unique_users` | Distinct users who downloaded (curated only) |
| `num_institutions` | Distinct institutions that downloaded (curated only) |
| `status` | `success` or `error` |
| `error_message` | Populated when `status == error`, or for non-fatal sub-fetch failures (e.g., title 404) |
| `timestamp` | When this row was scraped |

### Time-series CSV (curated only)

A second pair of files captures monthly downloads per study, going back to 2020:

- `nanda_usage_timeseries_YYYY-MM-DD.csv` — dated snapshot
- `nanda_usage_timeseries_latest.csv` — always overwritten with the most recent run

Long-format with one row per `(study_id, year, month)`. Months with zero activity are omitted.

| Column | Description |
|--------|-------------|
| `study_id` | ICPSR study ID (curated only) |
| `year` | Year of activity (e.g., 2024) |
| `month` | Month 1–12 |
| `data_downloads` | Data file downloads that month |
| `documentation_downloads` | Documentation downloads that month |
| `total_downloads` | Sum of the two |
| `timestamp` | When this snapshot was scraped (same value for every row in a run) |

openICPSR projects are excluded — PCMS doesn't expose a per-month feed for them.

### Delta report

After each scrape, `generate_delta.py` writes a Markdown summary comparing the current run to the most recent previous dated snapshot:

- `delta_YYYY-MM-DD.md` — dated snapshot
- `delta_latest.md` — always overwritten

Sections: headline totals + Δ%, top 5 absolute movers, top 5 % movers (baseline ≥ 50), anomalies (had downloads, now zero), new studies. The report runs automatically as part of the GHA workflow.

### Dashboard

`build_dashboard.py` writes a self-contained `dashboard/index.html` with:
- KPI cards (total downloads, dataset count, unique users)
- Aggregate monthly downloads chart (Chart.js, curated only)
- Sortable table of all 103 studies (click any column header)

Open the file directly in a browser, or enable GitHub Pages on the `dashboard/` folder in repo settings to publish at `https://the-national-neighborhood-data-archive.github.io/usage-metrics/` — no code change required.

## Limitations

- **No per-institution download counts.** PCMS's `/institution` endpoint returns institution metadata (name, location, type) but no download counts per institution. We expose `num_institutions` but not a top-institutions list.
- **openICPSR has no documentation/data split.** The openICPSR usage endpoint returns one `totalDownloads` figure with no breakdown.
- **Some openICPSR studies have no DOI.** Brand-new studies that haven't been registered with DOI return 404 on the title fetch; `dataset_title` is left blank and the 404 is logged in `error_message`.
- **No geographic breakdown.** PCMS does not expose a country/region/state download breakdown for studies. Verified by probing every plausible endpoint and inspecting the dashboard JS bundles; no such widget exists in the public utilization page.

## Adding a new study

Append the ID to the `STUDY_IDS` list at the top of `nanda_usage_scraper.py`, commit, push. The next monthly run picks it up automatically.

## Running locally

```bash
cd usage-metrics
pip install -r requirements.txt
python nanda_usage_scraper.py
```

Output goes to `data/`. Takes about 3 minutes for the full study list with the 1-second polite delay between requests.

## Debugging

If ICPSR changes their page structure or API, the diagnostic scripts in `debug/` are designed to find the new endpoints quickly:

- `debug/inspect_icpsr.py` — fetches a curated study DOI and dumps title, study metrics, JSON-LD, and inline scripts.
- `debug/openicpsr_probe.py` — fetches an openICPSR project page, finds the React component props, fetches the underlying JS file, and probes plausible API URLs.

Both write their output to a `.txt` file (no need to copy/paste from the terminal).

## Known risks

GitHub Actions sometimes runs from IP ranges Cloudflare treats as bot traffic. If a monthly run fails with a Cloudflare challenge, fall back to running `python nanda_usage_scraper.py` locally that day and committing the CSV manually.
