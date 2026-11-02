# Diagnosis: empty scrape in the 2026-11-01 update

**Date:** 2026-11-02 · **Status:** guardrail shipped, November 1 scrape quarantined, rerun pending (see the update at the end).

## Summary

The November 1 dashboard showed total downloads -15,561 and unique users -4,593 (down to 0). This was not an ICPSR history trim. ICPSR answered every request from the GitHub Actions runner with **HTTP 403 Forbidden**, on both hosts the scraper uses (`pcms.icpsr.umich.edu` and `www.icpsr.umich.edu`). The scraper recorded zeros, the run finished green, and the pipeline published the zeros. The same requests succeed from Lindsay's machine on November 2, so the block was specific to the runner, most likely Cloudflare or an ICPSR firewall rejecting GitHub's cloud IP addresses that day.

## 1. What the run did

- Run `41321612951` (scheduled, started 2026-11-01 15:31 UTC, about six hours after the 09:00 cron time) finished in 2 minutes 26 seconds with status **success**. Earlier monthly runs took 3 to 4.5 minutes.
- Every row of `nanda_usage_stats_2026-11-01.csv` carries a 403 in `error_message`:
  - 20 curated rows (PCMS `downloadCount`): `403 Client Error: Forbidden`, `scrape_status=error`.
  - 79 openICPSR rows (PCMS `openicpsr/projects/{id}/usage/view`): 403, but `scrape_status=success` with `total_downloads=0`.
  - 5 RDE rows (`www.icpsr.umich.edu/sites/api/usage-statistics-api`): 403, `scrape_status=success`, 0.
- The scraper's own summary line read `84 success / 20 errors / 0 with non-zero downloads`.
- `nanda_usage_timeseries_2026-11-01.csv` is header-only (0 rows). Every curated time-series request also got a 403.
- The log gives no response body or headers, so it can't say whether the 403 was a Cloudflare challenge page or an origin-server refusal. The scraper now logs both (see Fix).

## 2. Root cause

The 403 hit every endpoint on two separate ICPSR hosts within the same two minutes. A page-structure or API change would have produced parse errors, empty JSON, or 404s on one endpoint, not a uniform 403 everywhere. On 2026-11-02 the unchanged scraper, run from Lindsay's machine, got HTTP 200 and full data for curated 38528 (22,317 downloads, 882 unique users, monthly buckets through October 2026) and openICPSR 119451 (529 downloads). PCMS still returns the JSON shape the parser expects.

So the cause is outside this repo: ICPSR's edge refused traffic from the GitHub-hosted runner. `README.md` already noted that Cloudflare sometimes treats GitHub Actions IP ranges as bot traffic. Whether this was a one-day event or a lasting block is what the rerun tests.

Why it published anyway: the scraper treats openICPSR and RDE fetch failures as soft failures (row marked `success`, counts left at 0), and nothing between the scrape and the dashboard compared the new numbers to the previous ones.

## 3. Was the download history polluted?

**No downloads were lost.** `build_history.py` lets the newest snapshot win only for months that snapshot contains, and the empty November 1 time-series contained none. Comparing `nanda_download_history.csv` before and after the November 1 commit, all 766 `(study, year, month)` rows and every download count are identical. The only change: `in_latest_snapshot` flipped to `False` for every row, and no October 2026 rows were added. After quarantining the November 1 files and rerunning `build_history.py`, the history matches the October 1 build again.

The dashboard damage came from `nanda_usage_stats_latest.csv`: openICPSR and RDE totals and curated unique users are read from the latest snapshot, not the history, so they showed 0. Curated totals came from the history and held, which is why every curated row showed a change of 0.

## 4. Fix

1. **Quarantine.** The November 1 snapshot and time-series files moved to `data/quarantine/2026-11-01/`, filenames unchanged. Nothing was deleted. All downstream scripts glob only the top level of `data/`, so they no longer see these files.
2. **Loud failures in the scraper.** Every request now goes through `get_checked()`, which retries 403, 429, 5xx, and timeouts twice with a short wait, and on a final failure prints `WARN <study_id>` with the status code, `server`, `cf-mitigated`, and `cf-ray` headers and the start of the body. A PCMS response with no monthly buckets also prints a warning. The next block will show in the log whether it is a Cloudflare challenge (`cf-mitigated: challenge`).
3. **Guardrail.** `check_scrape.py` runs between the scrape and `build_history.py`. It fails if more than 25% of previously nonzero studies drop to 0 or go missing, if the time-series lacks the most recent complete month, or if curated unique users drop to 0. On failure the workflow quarantines the new dated files, commits only `data/quarantine/`, skips the history and dashboard builds, and ends red. Tested against the saved snapshots:
   - 2026-11-01 vs 2026-10-01: **fails** all three checks (102 of 102 studies zeroed, no October rows, 0 users).
   - 2026-08-01 vs 2026-07-01 (the real trim): **passes** (1 of 103 zeroed, 18 July rows, 4,459 users).
   - 2026-10-01 vs 2026-09-01: **passes**.

The retries cannot get past a lasting IP block. If ICPSR keeps refusing GitHub's runners, the options are running the scrape from Lindsay's machine (the existing fallback in `README.md`) or asking ICPSR to allow the traffic. Both are decisions for Lindsay, not code changes.
