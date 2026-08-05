# Diagnosis: negative usage deltas in the 2026-08-01 update

**Date:** 2026-08-05 · **Status:** diagnosis only — no pipeline code changed. Awaiting Lindsay's review before any fix ships.

## Summary

The August 1 report shows aggregate downloads −1,444 and unique users −341 against July 1. The cause is **not** a pipeline bug, a join error, a stale-file mismatch, or the RDE/GA4 migration. Between the July 1 and August 1 scrapes, **ICPSR's PCMS backend stopped serving download history older than July 2023**. Every legacy curated study's "lifetime" total silently shrank by exactly its Sept 2022–June 2023 activity. One additional openICPSR row (208906) dropped −97 due to a transient read timeout, which the delta report already flagged.

## 1. The file pairing is correct

- "Current" = `data/nanda_usage_stats_latest.csv`, byte-identical to `data/nanda_usage_stats_2026-08-01.csv` (verified by diff).
- "Previous" = `find_previous_snapshot()` → `files[-2]` = `data/nanda_usage_stats_2026-07-01.csv` (the dated Aug file is written before the delta runs, so `files[-2]` is genuinely July 1).
- Both snapshots have 105 rows, identical `study_id` sets, no duplicates, no unmatched rows in the outer merge. Join integrity is clean.

## 2. The per-dataset July → August diff

14 datasets decreased. All but one are `archive=ICPSR, deposit_via=legacy` (curated PCMS route); the RDE/GA4 rows actually **gained** (+27 net), ruling out the RDE-migration hypothesis.

| study_id | route | Jul downloads | Aug downloads | Δ downloads | Jul users | Aug users | Δ users |
|---|---|---:|---:|---:|---:|---:|---:|
| 38528 | ICPSR legacy | 21,494 | 21,104 | −390 | 914 | 845 | −69 |
| 38579 | ICPSR legacy | 1,809 | 1,451 | −358 | 91 | 70 | −21 |
| 38506 | ICPSR legacy | 4,860 | 4,575 | −285 | 861 | 788 | −73 |
| 38569 | ICPSR legacy | 2,462 | 2,181 | −281 | 136 | 110 | −26 |
| 38580 | ICPSR legacy | 3,975 | 3,781 | −194 | 161 | 145 | −16 |
| 38567 | ICPSR legacy | 1,558 | 1,390 | −168 | 206 | 181 | −25 |
| 38559 | ICPSR legacy | 975 | 852 | −123 | 140 | 121 | −19 |
| 38586 | ICPSR legacy | 5,354 | 5,257 | −97 | 378 | 358 | −20 |
| 208906 | openICPSR legacy | 97 | 0 | −97 | — | — | — |
| 38649 | ICPSR legacy | 2,226 | 2,135 | −91 | 229 | 200 | −29 |
| 38606 | ICPSR legacy | 746 | 665 | −81 | 160 | 141 | −19 |
| 38597 | ICPSR legacy | 3,899 | 3,831 | −68 | 204 | 194 | −10 |
| 38584 | ICPSR legacy | 1,898 | 1,843 | −55 | 237 | 225 | −12 |
| 38598 | ICPSR legacy | 3,180 | 3,143 | −37 | 246 | 239 | −7 |

## 3. Root cause: PCMS dropped ten months of history

The monthly time-series files expose exactly which historical months vanished between scrapes:

| snapshot | earliest month served | latest month |
|---|---|---|
| 2026-04-30 | **2022-09** | 2026-04 |
| 2026-05-01 | 2022-09 | 2026-04 |
| 2026-05-12 | 2022-09 | 2026-05 |
| 2026-05-13 | 2022-09 | 2026-05 |
| 2026-06-01 | 2022-09 | 2026-05 |
| 2026-07-01 | 2022-09 | 2026-06 |
| 2026-08-01 | **2023-07** | 2026-07 |

The left edge sat fixed at Sept 2022 for every snapshot since tracking began, then jumped to July 2023 in the August scrape. The 104 (study, year, month) rows for Sept 2022–June 2023 present on July 1 are simply absent on August 1 — 3,417 downloads of recorded history, gone.

Two corroborating facts:

- **Snapshot totals equal time-series sums exactly** (gap = 0 for all 19 curated studies in July). PCMS's `/downloadCount` "lifetime" total is just the sum of the monthly buckets it retains — so when buckets vanish, the total shrinks with them. Note this means the "since 01/01/2020" request window was *already* not honored before August: totals only ever covered Sept 2022 onward.
- **Live probe (Aug 5, 2026):** requesting `startDt=01/01/2020` today returns data starting 2023-07 for study 38528 (total 21,139 ≈ Aug 1's 21,104 + a few new August downloads) and 2023-08 for 38579 (total 1,451, matching the Aug 1 snapshot exactly). The truncation is on ICPSR's side, live, and reproducible.

### Per-study reconciliation (residual = 0 for every study)

For each curated study: `Aug total = Jul total − (Sept 2022–Jun 2023 history) + (new activity since June)`. This closes **exactly**, with zero residual, for all 15 studies that had any activity in the dropped window:

| study_id | Jul total | Aug total | Δ | history lost | new activity | predicted Δ | residual |
|---|---:|---:|---:|---:|---:|---:|---:|
| 38528 | 21,494 | 21,104 | −390 | 966 | 576 | −390 | 0 |
| 38579 | 1,809 | 1,451 | −358 | 376 | 18 | −358 | 0 |
| 38506 | 4,860 | 4,575 | −285 | 374 | 89 | −285 | 0 |
| 38569 | 2,462 | 2,181 | −281 | 308 | 27 | −281 | 0 |
| 38580 | 3,975 | 3,781 | −194 | 236 | 42 | −194 | 0 |
| 38567 | 1,558 | 1,390 | −168 | 192 | 24 | −168 | 0 |
| 38559 | 975 | 852 | −123 | 137 | 14 | −123 | 0 |
| 38586 | 5,354 | 5,257 | −97 | 206 | 109 | −97 | 0 |
| 38649 | 2,226 | 2,135 | −91 | 113 | 22 | −91 | 0 |
| 38606 | 746 | 665 | −81 | 92 | 11 | −81 | 0 |
| 38597 | 3,899 | 3,831 | −68 | 139 | 71 | −68 | 0 |
| 38584 | 1,898 | 1,843 | −55 | 97 | 42 | −55 | 0 |
| 38598 | 3,180 | 3,143 | −37 | 91 | 54 | −37 | 0 |
| 38585 | 1,303 | 1,329 | +26 | 10 | 36 | +26 | 0 |
| 38605 | 2,707 | 2,761 | +54 | 80 | 134 | +54 | 0 |

Two studies (38585, 38605) also lost history but gained enough new downloads to stay net positive — the truncation hit 15 studies, not just the 13 that show negative.

### Aggregate accounting

The identified causes fully explain the headline numbers:

- **Downloads (−1,444):** curated truncation −3,417 + curated new activity +1,269 = −2,148 across the 15 truncated studies; +704 from the 5 curated studies with no activity in the dropped window (39093 +618, 39378 +79, others +7); −97 from the 208906 timeout; +70 from other openICPSR legacy rows; +27 from RDE rows. Net: **−1,444** ✓
- **Unique users (−341):** entirely within curated studies (−355 negative, +14 positive; openICPSR/RDE rows carry no user counts). Same mechanism — `/downloadInfo` counts distinct users over the window PCMS retains, so users whose only downloads fell in Sept 2022–June 2023 no longer count. ✓

### The 208906 outlier is separate

`208906` (Personal Care Services and Laundry) hit a 30-second read timeout on the openICPSR endpoint (`error_message`: "openicpsr-usage fallback: … Read timed out") and wrote 0. The existing drop-to-zero check caught it — it's the one row in the report's "Possible scrape problems" section. Transient; it should self-correct on Sept 1.

## 4. Data bug or legitimate source revision?

**Source-side revision** (with one transient scrape failure). The scraper faithfully recorded what PCMS served on each date. The July 2023 boundary is suggestive: Google Universal Analytics stopped processing on July 1, 2023, and GA4 became mandatory — ICPSR most likely purged (or stopped bridging) pre-GA4-era analytics data. Whether this is a **one-time purge** (boundary stays at 2023-07) or a new **rolling ~3-year cap** (boundary advances monthly, producing fresh negatives every month) can't be distinguished yet — the edge hasn't moved between Aug 1 and Aug 5. **The Sept 1 run is the test:** if the earliest month becomes 2023-08, it's a rolling cap.

Worth raising with Kyrani either way: NaNDA's public "total downloads" figures just quietly dropped, and ICPSR may not have announced the retention change.

## 5. Recommended fix: flag and annotate — do not clamp to zero

**Recommendation: flag-and-annotate.** Clamping negatives to zero would misrepresent a real, systematic source event as "no activity," break the arithmetic tie between the delta report and the snapshot CSVs, and hide exactly the signal that let us diagnose this. The negatives are information.

Concretely (for the follow-up pass, once approved):

1. **`generate_delta.py`** — add a "Cumulative totals that decreased" section, parallel to the existing drop-to-zero section, listing each study whose total fell, with a stock annotation: cumulative counts can only legitimately fall when the source revises or truncates its history; treat these rows' "change" as a source revision, not lost downloads. Exclude decreased rows from the "most new downloads" ranking (they already sort out naturally) and footnote the headline net change when any decreases are present, splitting it into "new downloads" vs "source revision."
2. **Timeout rows** — treat rows whose `error_message` is populated and whose value fell to 0 as *non-comparable* (excluded from the delta and the headline sums, listed in the scrape-problems section as they are today) rather than as genuine zeros. That's the flag-not-clamp principle applied to the 208906 case: −97 of this month's headline drop is a measurement artifact, not a source revision.
3. **Dashboard** — show a small annotation on any month where the aggregate fell, linking the explanation ("ICPSR revised its historical data in Aug 2026"), rather than suppressing the dip. The trend line should show what the source reported.
4. **Guard for the future** — a post-scrape check comparing each study's new total against the prior snapshot; if any cumulative metric fell, write a warning block into the delta report (and optionally fail the Actions job with a visible annotation) so the next truncation is noticed the day it happens, not weeks later. Also worth logging the time-series' earliest served month each run — a one-line canary that catches window truncation directly.
5. **Longer-term option (separate discussion)** — the repo's own archived snapshots retain the Sept 2022–June 2023 monthly buckets PCMS no longer serves. True cumulative series could be reconstructed locally by unioning archived time-series files, insulating the dashboard from future source truncation.

## Verification notes

- Files compared: `nanda_usage_stats_latest.csv` (≡ `nanda_usage_stats_2026-08-01.csv`, verified byte-identical) vs `nanda_usage_stats_2026-07-01.csv`. Pairing confirmed correct.
- No changes made to `nanda_usage_scraper.py`, `generate_delta.py`, `build_dashboard.py`, the workflow, or any snapshot. The only live API access was two read-only GET probes of PCMS `downloadCount`.
- Analysis scripts and merged diff CSV live in the session scratchpad, not the repo.
