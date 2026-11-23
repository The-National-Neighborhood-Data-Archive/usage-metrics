# Vocabulary

Plain-language definitions of the status and category terms used in this repo. The private
[nanda-inventory VOCABULARY.md](https://github.com/The-National-Neighborhood-Data-Archive/nanda-inventory/blob/main/VOCABULARY.md)
(org members only) covers the dataset-identity terms (`deposit_state`, `related_to_doi`,
`topic_folder`, `topic_review`, `sheet_status`, hand-review).

| Term | Where it lives | Values | Meaning |
|------|----------------|--------|---------|
| `status` | `inventory.csv` | `published`, `unpublished` | Publication axis: whether this deposit is part of the current published release set. `unpublished` rows are kept in the inventory but shown in their own dashboard table; most are older openICPSR deposits. Exported unchanged each week from the `pub_status` column of nanda-inventory's `deposit_status.csv` (see its VOCABULARY.md). |
| `pub_status` | `build_dashboard.py`, in memory only | same as `status` | The dashboard's alias for inventory `status` after it merges the inventory into the latest snapshot. Snapshots dated before 2026-08 call the scrape-outcome column `status`, so the rename keeps the two from colliding. Never written to a file. |
| `scrape_status` | snapshot CSVs (`nanda_usage_stats_*.csv`) | `success`, `error` | Did this row's scrape work in this run. Says nothing about publication. Snapshots dated before 2026-08 call this column `status`. |
| `archive` | `inventory.csv` | `ICPSR`, `openICPSR` | Which catalog the deposit was made in. It drives the dashboard's curated vs. self-published split and the scraper's routing: `openICPSR` rows ask both usage sources and add them; `ICPSR` rows pick one source by `deposit_via`. |
| `deposit_via` | `inventory.csv` | `legacy`, `RDE` | Which deposit pathway was used. For `archive=ICPSR` rows, `RDE` sends the row to the NaNDA usage-statistics API instead of PCMS. For `archive=openICPSR` rows it no longer picks the usage source (since 2026-11-23; every openICPSR deposit now lives in ICPSR's self-deposit system, so all of them ask both sources). New deposits default to `RDE`; `legacy` is for pre-RDE backfills. |
| `earlier_version_downloads` | snapshot CSVs, since the 2026-12 snapshot | integer, blank for curated rows | For `archive=openICPSR` rows: downloads of the earlier version of the dataset, from the openICPSR usage endpoint. ICPSR moved the deposits in 2026, so this count has mostly stopped growing. |
| `current_deposit_downloads` | snapshot CSVs, since the 2026-12 snapshot | integer, blank for curated rows | For `archive=openICPSR` rows: downloads of the current deposit, from the usage-statistics endpoint of ICPSR's self-deposit system. `total_downloads` for these rows is the sum of the two. |
| curated | dashboard wording and `build_dashboard.py` | derived, not stored | Today this means `archive == ICPSR`, whatever the `deposit_via` value. ICPSR has begun moving curated studies onto RDE, and how those rows should display is undecided and parked. Study ID length is not a signal of curated vs. self-deposited (305511 is a curated ICPSR study with six digits). |
| self-published | dashboard wording and `build_dashboard.py` | derived, not stored | `archive == openICPSR` and `status` is not `unpublished`. Deposited through ICPSR's self-deposit system (formerly openICPSR). The dashboard shows both usage sources and their sum for these rows. |
| unpublished | dashboard wording and `build_dashboard.py` | derived, not stored | `status == unpublished`, any archive. Shown in the dashboard's third table. |
