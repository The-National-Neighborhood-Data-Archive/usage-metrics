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
NANDA_PREFIX = "National Neighborhood Data Archive (NaNDA): "


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
    if s.startswith(NANDA_PREFIX):
        s = s[len(NANDA_PREFIX):]
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


def section_anomalies(comp: pd.DataFrame) -> str:
    anomaly = comp[(comp["total_downloads_prev"] > 0) & (comp["total_downloads"] == 0)]
    if anomaly.empty:
        return "_None._"
    rows = ["| ID | Dataset | Was | Now |",
            "|---|---|---:|---:|"]
    for _, r in anomaly.sort_values("total_downloads_prev", ascending=False).iterrows():
        rows.append(f"| {int(r['study_id'])} | {truncate(r['dataset_title'])} | "
                    f"{fmt_int(r['total_downloads_prev'])} | {fmt_int(r['total_downloads'])} |")
    return "\n".join(rows)


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

    # Studies that exist in both = comparable
    comp = merged[
        merged["total_downloads"].notna() & merged["total_downloads_prev"].notna()
    ].copy()
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

    parts = [
        f"# NaNDA usage report — {today}",
        f"_What changed since the last snapshot on {prev_date}._",
        "",
        "## At a glance",
        "",
        f"- **Total downloads across all of NaNDA:** {total_curr:,} (was {total_prev:,})",
        f"- **Net change:** {fmt_signed(total_delta)} ({fmt_pct(total_pct)})",
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
        "## Possible scrape problems",
        "_These had downloads last time but show zero now — probably a glitch pulling data, worth a look._",
        "",
        section_anomalies(comp),
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
