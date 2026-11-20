# Vocabulary

Plain-language definitions of the status and category terms used in this repo. The private
[nanda-inventory VOCABULARY.md](https://github.com/The-National-Neighborhood-Data-Archive/nanda-inventory/blob/main/VOCABULARY.md)
(org members only) covers the dataset-identity terms (`deposit_state`, `related_to_doi`,
`topic_folder`, `topic_review`, `sheet_status`, hand-review).

| Term | Where it lives | Values | Meaning |
|------|----------------|--------|---------|
| `status` | `inventory.csv` | `published`, `unpublished` | Publication axis: whether this deposit is part of the current published release set. `unpublished` rows are kept in the inventory but shown in their own dashboard table; most are older openICPSR deposits. The weekly export from nanda-inventory derives this from `deposit_state` (see its VOCABULARY.md) and passes existing `unpublished` rows through untouched. |
| `pub_status` | `build_dashboard.py`, in memory only | same as `status` | The dashboard's alias for inventory `status` after it merges the inventory into the latest snapshot. Snapshots dated before 2026-08 call the scrape-outcome column `status`, so the rename keeps the two from colliding. Never written to a file. |
| `scrape_status` | snapshot CSVs (`nanda_usage_stats_*.csv`) | `success`, `error` | Did this row's scrape work in this run. Says nothing about publication. Snapshots dated before 2026-08 call this column `status`. |
| `archive` | `inventory.csv` | `ICPSR`, `openICPSR` | Which catalog the deposit lives in. For `deposit_via=legacy` rows it picks the API endpoint set. It also drives the dashboard's curated vs. self-published split. |
| `deposit_via` | `inventory.csv` | `legacy`, `RDE` | Which deposit pathway was used. `RDE` is checked first in routing and sends the row to the NaNDA usage-statistics API regardless of `archive`. New deposits default to `RDE`; `legacy` is for pre-RDE backfills. |
| curated | dashboard wording and `build_dashboard.py` | derived, not stored | Today this means `archive == ICPSR`, whatever the `deposit_via` value. ICPSR has begun moving curated studies onto RDE, and how those rows should display is undecided and parked. Study ID length is not a signal of curated vs. self-deposited (305511 is a curated ICPSR study with six digits). |
| self-published | dashboard wording and `build_dashboard.py` | derived, not stored | `archive == openICPSR` and `status` is not `unpublished`. |
| unpublished | dashboard wording and `build_dashboard.py` | derived, not stored | `status == unpublished`, any archive. Shown in the dashboard's third table. |
