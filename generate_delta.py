#!/usr/bin/env python3
"""
Generate a Markdown delta report comparing the latest scrape to the
most recent previous dated snapshot.

Reads:
  data/nanda_usage_stats_latest.csv
  data/nanda_usage_stats_YYYY-MM-DD.csv  (most recent strict-pattern file
                                          before today's; ignores _revised
                                          and _latest)

Writes:
  data/delta_{today}.md
  data/delta_latest.md

If no previous snapshot exists, writes a short stub.
"""

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
LATEST_CSV = DATA_DIR / "nanda_usage_stats_latest.csv"
DATED_RE = re.compile(r"^nanda_usage_stats_(\d{4}-\d{2}-\d{2})\.csv$")
TOP_N = 5
PCT_BASELINE_MIN = 50  # ignore studies with previous < 50 for % movers
TITLE_TRUNC = 70


def find_previous_snapshot():
    """Return (date_str, path) of the second-most-recent strict-pattern CSV."""
    files = []
    for f in DATA_DIR.glob("nanda_usage_stats_*.csv"):
        m = DATED_RE.match(f.name)
        if m:
            files.append((m.group(1), f))
    files.sort(key=lambda x: x[0])
    if len(files) < 2:
        return None
    return files[-2]


def fmt_int(n) -> str:
    return f"{int(n):,}" if pd.notna(n) else "—"


def fmt_pct(p) -> str:
    if pd.isna(p):
        return "—"
    sign = "+" if p > 0 else ""
    return f"{sign}{p:.1f}%"


def fmt_signed(d) -> str:
    if pd.isna(d):
        return "—"
    sign = "+" if d > 0 else ""
    return f"{sign}{int(d):,}"


def truncate(s, n=TITLE_TRUNC) -> str:
    if pd.isna(s) or not s:
        return "—"
    s = str(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def section_top_absolute(comp: pd.DataFrame) -> str:
    df = comp.sort_values("delta_abs", ascending=False).head(TOP_N)
    if df.empty:
        return "_No comparable studies._"
    rows = ["| ID | Dataset | Was | Now | Change |",
            "|---|---|---:|---:|---:|"]
    for _, r in df.iterrows():
        rows.append(f"| {int(r['study_id'])} | {truncate(r['dataset_title'])} | "
                    f"{fmt_int(r['total_downloads_prev'])} | {fmt_int(r['total_downloads'])} | "
                    f"{fmt_signed(r['delta_abs'])} |")
    return "\n".join(rows)


def section_top_pct(comp: pd.DataFrame) -> str:
    eligible = comp[comp["total_downloads_prev"] >= PCT_BASELINE_MIN]
    df = eligible.sort_values("delta_pct", ascending=False).head(TOP_N)
    if df.empty:
        return f"_No studies with previous downloads ≥ {PCT_BASELINE_MIN}._"
    rows = ["| ID | Dataset | Was | Now | % change |",
            "|---|---|---:|---:|---:|"]
    for _, r in df.iterrows():
        rows.append(f"| {int(r['study_id'])} | {truncate(r['dataset_title'])} | "
                    f"{fmt_int(r['total_downloads_prev'])} | {fmt_int(r['total_downloads'])} | "
                    f"{fmt_pct(r['delta_pct'])} |")
    return "\n".join(rows)


def section_anomalies(suspect: pd.DataFrame) -> str:
    if suspect.empty:
        return "_None._"
    rows = ["| ID | Dataset | Was | Now | Error |",
            "|---|---|---:|---:|---|"]
    for _, r in suspect.sort_values("total_downloads_prev", ascending=False).iterrows():
        rows.append(f"| {int(r['study_id'])} | {truncate(r['dataset_title'])} | "
                    f"{fmt_int(r['total_downloads_prev'])} | {fmt_int(r['total_downloads'])} | "
                    f"{truncate(r.get('error_message'), 60)} |")
    return "\n".join(rows)


def section_decreased(comp: pd.DataFrame) -> str:
    df = comp[comp["delta_abs"] < 0].sort_values("delta_abs")
    if df.empty:
        return "_None._"
    rows = ["| ID | Dataset | Was | Now | Change |",
            "|---|---|---:|---:|---:|"]
    for _, r in df.iterrows():
        rows.append(f"| {int(r['study_id'])} | {truncate(r['dataset_title'])} | "
                    f"{fmt_int(r['total_downloads_prev'])} | {fmt_int(r['total_downloads'])} | "
                    f"{fmt_signed(r['delta_abs'])} |")
    return "\n".join(rows)


def timeseries_window_shift(prev_date: str):
    """
    Compare the earliest month served in the current vs. previous
    time-series snapshot. PCMS retains a bounded history window; when
    its left edge advances, cumulative totals silently shrink by the
    activity that fell out (first observed 2026-08: Sept 2022–June 2023
    dropped). Returns ('YYYY-MM', 'YYYY-MM') when the edge advanced,
    else None.
    """
    curr_p = DATA_DIR / "nanda_usage_timeseries_latest.csv"
    prev_p = DATA_DIR / f"nanda_usage_timeseries_{prev_date}.csv"
    if not (curr_p.exists() and prev_p.exists()):
        return None

    def earliest(path):
        ts = pd.read_csv(path, usecols=["year", "month"])
        if ts.empty:
            return None
        ym = int((ts["year"] * 100 + ts["month"]).min())
        return f"{ym // 100:04d}-{ym % 100:02d}"

    prev_edge, curr_edge = earliest(prev_p), earliest(curr_p)
    if prev_edge and curr_edge and curr_edge > prev_edge:
        return prev_edge, curr_edge
    return None


def section_new_studies(new_df: pd.DataFrame) -> str:
    if new_df.empty:
        return "_None._"
    rows = ["| ID | Dataset | Total downloads |",
            "|---|---|---:|"]
    for _, r in new_df.sort_values("total_downloads", ascending=False).iterrows():
        rows.append(f"| {int(r['study_id'])} | {truncate(r['dataset_title'])} | "
                    f"{fmt_int(r['total_downloads'])} |")
    return "\n".join(rows)


def main() -> None:
    if not LATEST_CSV.exists():
        print(f"Missing {LATEST_CSV} — run the scraper first")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    out_dated  = DATA_DIR / f"delta_{today}.md"
    out_latest = DATA_DIR / "delta_latest.md"

    current = pd.read_csv(LATEST_CSV)

    prev = find_previous_snapshot()
    if prev is None:
        body = (f"# NaNDA Usage Delta — {today}\n\n"
                f"_No previous snapshot found to compare against._\n")
        out_dated.write_text(body, encoding="utf-8")
        out_latest.write_text(body, encoding="utf-8")
        print(f"Wrote {out_dated} (no comparison)")
        return

    prev_date, prev_path = prev
    previous = pd.read_csv(prev_path)

    # Outer-merge on study_id; "_prev" suffix on previous's total_downloads
    merged = current.merge(
        previous[["study_id", "total_downloads"]].rename(
            columns={"total_downloads": "total_downloads_prev"}
        ),
        on="study_id", how="outer",
    )

    # Studies in current that are missing from previous = new
    new_mask = merged["total_downloads_prev"].isna() & merged["total_downloads"].notna()
    new_df = merged[new_mask].copy()

    # Studies that exist in both snapshots
    both = merged["total_downloads"].notna() & merged["total_downloads_prev"].notna()

    # Rows that fell to zero are non-comparable measurements (scrape
    # failures until proven otherwise) — reported separately, excluded
    # from the movers rankings and the net-change decomposition.
    suspect_mask = both & (merged["total_downloads"] == 0) & (merged["total_downloads_prev"] > 0)
    suspect = merged[suspect_mask].copy()

    comp = merged[both & ~suspect_mask].copy()
    comp["delta_abs"] = comp["total_downloads"] - comp["total_downloads_prev"]
    comp["delta_pct"] = pd.NA
    nonzero_prev = comp["total_downloads_prev"] > 0
    comp.loc[nonzero_prev, "delta_pct"] = (
        comp.loc[nonzero_prev, "delta_abs"] / comp.loc[nonzero_prev, "total_downloads_prev"] * 100
    )

    # Headline totals
    total_curr = int(current["total_downloads"].sum())
    total_prev = int(previous["total_downloads"].sum())
    total_delta = total_curr - total_prev
    total_pct = (total_delta / total_prev * 100) if total_prev else None

    # Decompose the net change: genuine new downloads vs. source-side
    # downward revisions vs. scrape-error rows vs. newly tracked datasets.
    gained = int(comp.loc[comp["delta_abs"] > 0, "delta_abs"].sum())
    revised = int(comp.loc[comp["delta_abs"] < 0, "delta_abs"].sum())  # ≤ 0
    suspect_delta = int((suspect["total_downloads"] - suspect["total_downloads_prev"]).sum())
    new_total = int(new_df["total_downloads"].sum()) if not new_df.empty else 0

    net_line = f"- **Net change:** {fmt_signed(total_delta)} ({fmt_pct(total_pct)})"
    if revised < 0 or not suspect.empty:
        pieces = [f"{fmt_signed(gained)} new downloads"]
        if new_total:
            pieces.append(f"{fmt_signed(new_total)} from newly tracked datasets")
        if revised < 0:
            pieces.append(f"{fmt_signed(revised)} source revision")
        if not suspect.empty:
            pieces.append(f"{fmt_signed(suspect_delta)} across {len(suspect)} "
                          f"dataset{'s' if len(suspect) != 1 else ''} with scrape errors")
        net_line += " — " + " · ".join(pieces)

    # Canary: did the source's history window lose months since last time?
    warn_block = []
    shift = timeseries_window_shift(prev_date)
    if shift:
        prev_edge, curr_edge = shift
        warn_block = [
            "",
            f"> ⚠️ **Source history window moved.** The earliest month of download "
            f"history ICPSR serves advanced from {prev_edge} to {curr_edge}. "
            f"Cumulative totals shrank by whatever activity fell out of that "
            f"window — see “Cumulative totals that decreased.”",
        ]
        print(f"::warning title=ICPSR history window moved::earliest served month "
              f"advanced from {prev_edge} to {curr_edge}; cumulative totals "
              f"decreased accordingly")

    parts = [
        f"# NaNDA usage report — {today}",
        f"_What changed since the last snapshot on {prev_date}._",
        *warn_block,
        "",
        "## At a glance",
        "",
        f"- **Total downloads across all of NaNDA:** {total_curr:,} (was {total_prev:,})",
        net_line,
        f"- **Datasets in this report:** {len(current)} ({len(new_df)} new since {prev_date})",
        "",
        "## Datasets with the most new downloads",
        "",
        section_top_absolute(comp),
        "",
        "## Datasets with the highest percentage of new downloads",
        f"_Only counts datasets that had at least {PCT_BASELINE_MIN} downloads to start with — keeps the percentages meaningful._",
        "",
        section_top_pct(comp),
        "",
        "## Cumulative totals that decreased",
        "_Lifetime counts only fall when ICPSR revises or truncates its own historical data — treat these as source-side revisions, not lost downloads. (Datasets that fell to zero appear under “Possible scrape problems” instead.)_",
        "",
        section_decreased(comp),
        "",
        "## Possible scrape problems",
        "_These had downloads last time but show zero now — probably a glitch pulling data, worth a look. They're excluded from the movers and the net-change breakdown above._",
        "",
        section_anomalies(suspect),
        "",
        f"## Datasets we started tracking since {prev_date}",
        "",
        section_new_studies(new_df),
        "",
    ]

    body = "\n".join(parts)
    out_dated.write_text(body, encoding="utf-8")
    out_latest.write_text(body, encoding="utf-8")
    print(f"Wrote {out_dated}")
    print(f"Wrote {out_latest}")


if __name__ == "__main__":
    main()
