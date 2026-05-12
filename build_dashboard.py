#!/usr/bin/env python3
"""
Build a single-file static dashboard summarizing the latest NaNDA usage
scrape. Reads the three artifacts produced by the scraper and writes a
self-contained `docs/index.html` with inline CSS and Chart.js from
CDN.

Inputs:
  data/nanda_usage_stats_latest.csv
  data/nanda_usage_timeseries_latest.csv
  data/nanda_usage_stats_YYYY-MM-DD.csv  (most recent strict-pattern file
                                          before today's, for Δ computation)
  inventory.csv                          (for archive routing: ICPSR vs openICPSR)
  docs/assets/nanda-logo.svg             (NaNDA wordmark, served alongside HTML)

Output:
  docs/index.html

Lives in `docs/` because GitHub Pages only allows publishing from `/` or
`/docs` — not arbitrary subfolders. To publish: Settings → Pages → branch
main → folder /docs.
"""

import html
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
OUTPUT_DIR = Path("docs")
LATEST_CSV  = DATA_DIR / "nanda_usage_stats_latest.csv"
TIMESERIES_CSV = DATA_DIR / "nanda_usage_timeseries_latest.csv"
INVENTORY_CSV = Path("inventory.csv")
DATED_RE = re.compile(r"^nanda_usage_stats_(\d{4}-\d{2}-\d{2})\.csv$")

NANDA_HOMEPAGE = "https://nanda.isr.umich.edu/"
GITHUB_REPO = "https://github.com/the-national-neighborhood-data-archive/usage-metrics"


def find_dated_snapshots():
    """Return all dated snapshot files sorted ascending by ISO date."""
    files = []
    for f in DATA_DIR.glob("nanda_usage_stats_*.csv"):
        m = DATED_RE.match(f.name)
        if m:
            files.append((m.group(1), f))
    files.sort(key=lambda x: x[0])
    return files


def fmt_int(n):
    if pd.isna(n):
        return ""
    return f"{int(n):,}"


def fmt_signed(n):
    if pd.isna(n) or n is None:
        return ""
    n = int(n)
    if n == 0:
        return "0"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:,}"


def fmt_human_date(iso_date):
    """'2026-05-01' -> 'May 1, 2026' (cross-platform; avoids %-d / %#d)."""
    if not iso_date:
        return ""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def fmt_human_month(ym):
    """'2024-03' -> 'March 2024'."""
    dt = datetime.strptime(ym, "%Y-%m")
    return f"{dt.strftime('%B')} {dt.year}"


def chart_trend_summary(labels, values):
    """One-sentence summary for screen readers via aria-label."""
    if not values:
        return "Aggregate monthly downloads chart. No data available."
    peak_idx = values.index(max(values))
    direction = (
        "increasing overall"
        if values[-1] > values[0]
        else "decreasing overall"
        if values[-1] < values[0]
        else "flat overall"
    )
    return (
        f"Aggregate monthly downloads of curated NaNDA datasets, "
        f"{fmt_human_month(labels[0])} through {fmt_human_month(labels[-1])}. "
        f"Started at {values[0]:,} downloads in {fmt_human_month(labels[0])}, "
        f"peaked at {values[peak_idx]:,} in {fmt_human_month(labels[peak_idx])}, "
        f"ended at {values[-1]:,} in {fmt_human_month(labels[-1])}. "
        f"Trend is {direction}."
    )


def main() -> None:
    if not LATEST_CSV.exists():
        print(f"Missing {LATEST_CSV} — run the scraper first")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Source of truth for "data freshness" is the latest dated snapshot file.
    # Fall back to today only if the pipeline has never produced a dated file.
    snapshots = find_dated_snapshots()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    if snapshots:
        latest_iso = snapshots[-1][0]
    else:
        latest_iso = today_iso
    latest_human = fmt_human_date(latest_iso)

    current = pd.read_csv(LATEST_CSV)

    # --- Archive routing + publication status from inventory ---
    # Inventory's `status` column collides with the scraper's per-row
    # success/error `status`, so rename on merge to `pub_status`.
    if INVENTORY_CSV.exists():
        inv = (
            pd.read_csv(INVENTORY_CSV)[["study_id", "archive", "status"]]
            .rename(columns={"status": "pub_status"})
        )
        current = current.merge(inv, on="study_id", how="left")
    else:
        current["archive"] = "ICPSR"  # fallback; should never hit in CI
        current["pub_status"] = "published"

    # --- Δ computation against most recent prior snapshot ---
    prev = snapshots[-2] if len(snapshots) >= 2 else None
    if prev is None:
        prev_date_iso = None
        prev_date_human = None
        prev_df = None
        delta_total = None
        delta_n_datasets = None
        delta_unique_users = None
    else:
        prev_date_iso, prev_path = prev
        prev_date_human = fmt_human_date(prev_date_iso)
        prev_df = pd.read_csv(prev_path)
        delta_total = int(current["total_downloads"].sum() - prev_df["total_downloads"].sum())
        delta_n_datasets = int(len(current) - len(prev_df))
        prev_users = int(prev_df["unique_users"].fillna(0).sum())
        cur_users = int(current["unique_users"].fillna(0).sum())
        delta_unique_users = cur_users - prev_users

    # Per-row deltas via merge
    if prev_df is not None:
        merged = current.merge(
            prev_df[["study_id", "total_downloads"]].rename(
                columns={"total_downloads": "_prev"}
            ),
            on="study_id", how="left",
        )
        merged["delta"] = merged["total_downloads"] - merged["_prev"]
    else:
        merged = current.copy()
        merged["delta"] = pd.NA

    # --- KPIs ---
    total_downloads = int(current["total_downloads"].sum())
    n_datasets = len(current)
    unique_users_total = int(current["unique_users"].fillna(0).sum())

    # --- Time-series aggregate ---
    if TIMESERIES_CSV.exists():
        ts = pd.read_csv(TIMESERIES_CSV)
        monthly = (ts.groupby(["year", "month"], as_index=False)["total_downloads"]
                     .sum()
                     .sort_values(["year", "month"]))
        ts_labels = [f"{int(y)}-{int(m):02d}" for y, m in zip(monthly["year"], monthly["month"])]
        ts_values = [int(v) for v in monthly["total_downloads"]]
    else:
        ts_labels, ts_values = [], []

    trend_summary = chart_trend_summary(ts_labels, ts_values)

    # --- Studies table rows ---
    table_rows = []
    for _, r in merged.iterrows():
        title = r.get("dataset_title")
        title_str = "" if pd.isna(title) else str(title)
        doi = r.get("doi")
        doi_str = "" if pd.isna(doi) else str(doi)
        url = r.get("url")
        url_str = "" if pd.isna(url) else str(url)
        archive = r.get("archive") or "ICPSR"
        pub_status = r.get("pub_status") or "published"
        table_rows.append({
            "study_id":   int(r["study_id"]),
            "title":      title_str,
            "doi":        doi_str,
            "url":        url_str,
            "archive":    archive,
            "pub_status": pub_status,
            "total":      int(r["total_downloads"]) if pd.notna(r["total_downloads"]) else 0,
            "delta":      None if pd.isna(r["delta"]) else int(r["delta"]),
            "users":      None if pd.isna(r.get("unique_users")) else int(r["unique_users"]),
            "pubs":       None if pd.isna(r.get("publications")) else int(r["publications"]),
            "views":      None if pd.isna(r.get("total_views")) else int(r["total_views"]),
        })

    curated_rows = [r for r in table_rows if r["archive"] == "ICPSR"]
    self_rows = [r for r in table_rows
                 if r["archive"] == "openICPSR" and r["pub_status"] != "unpublished"]
    unpublished_rows = [r for r in table_rows if r["pub_status"] == "unpublished"]

    # --- Render helpers ---
    def title_link(row):
        title_safe = html.escape(row["title"])
        if row["doi"]:
            href = "https://doi.org/" + row["doi"]
            return f'<a href="{html.escape(href)}">{title_safe}</a>'
        if row["url"]:
            return f'<a href="{html.escape(row["url"])}">{title_safe}</a>'
        return title_safe

    def delta_cell(row):
        if row["delta"] is None:
            return '<td class="num" data-sort=""><span class="muted">—</span></td>'
        cls = ""
        if row["delta"] > 0:
            cls = " delta-pos"
        elif row["delta"] < 0:
            cls = " delta-neg"
        return (
            f'<td class="num{cls}" data-sort="{row["delta"]}">'
            f'{fmt_signed(row["delta"])}'
            f'</td>'
        )

    def num_cell(value):
        if value is None:
            return '<td class="num" data-sort=""><span class="muted">—</span></td>'
        return f'<td class="num" data-sort="{value}">{value:,}</td>'

    def render_curated_tbody():
        out = []
        for row in curated_rows:
            out.append(
                f"<tr data-study-id=\"{row['study_id']}\">"
                f"<td class=\"title-cell\">{title_link(row)}</td>"
                f"<td class=\"num\" data-sort=\"{row['total']}\">{row['total']:,}</td>"
                f"{delta_cell(row)}"
                f"{num_cell(row['users'])}"
                f"{num_cell(row['pubs'])}"
                "</tr>"
            )
        return "\n".join(out)

    def render_openicpsr_tbody(rows):
        out = []
        for row in rows:
            out.append(
                f"<tr data-study-id=\"{row['study_id']}\">"
                f"<td class=\"title-cell\">{title_link(row)}</td>"
                f"{num_cell(row['views'])}"
                f"<td class=\"num\" data-sort=\"{row['total']}\">{row['total']:,}</td>"
                f"{delta_cell(row)}"
                "</tr>"
            )
        return "\n".join(out)

    # --- KPI delta rendering ---
    # Window is explicit ("from X to Y") so readers don't have to guess
    # whether the delta covers a day, a month, or anything in between.
    def kpi_delta_html(delta, kind="num"):
        if delta is None or prev_date_iso is None:
            return '<dd class="kpi-delta muted">— no prior snapshot</dd>'
        if delta == 0:
            sign_cls = ""
            text = f"No change {prev_date_human} to {latest_human}"
        else:
            sign_cls = " delta-pos" if delta > 0 else " delta-neg"
            text = f"{fmt_signed(delta)} {prev_date_human} to {latest_human}"
        return f'<dd class="kpi-delta{sign_cls}">{html.escape(text)}</dd>'

    # --- Hidden chart data table for screen readers ---
    chart_data_rows = "\n".join(
        f"<tr><td>{fmt_human_month(lbl)}</td><td>{val:,}</td></tr>"
        for lbl, val in zip(ts_labels, ts_values)
    )

    curated_count = len(curated_rows)
    self_count = len(self_rows)
    unpublished_count = len(unpublished_rows)

    # --- Definitions (used in tooltips/footnotes) ---
    curated_def = (
        "Datasets that went through ICPSR's full curation pipeline. "
        "Curated releases ship with documentation, codebooks, and per-month usage breakdowns; "
        "they live at icpsr.umich.edu and report unique users, institutions, and citing publications."
    )
    self_def = (
        "Datasets self-deposited via openICPSR. Self-published releases skip the full curation pipeline, "
        "so usage reporting is limited to total downloads and total project-page views — no per-month "
        "breakdown, unique-user count, or publication tracking."
    )
    unpublished_def = (
        "Datasets in NaNDA's inventory marked status=unpublished — openICPSR deposits "
        "that are not part of the current published release set (typically older or "
        "superseded versions). Usage reporting matches self-published: total downloads "
        "and total project-page views only, no per-month breakdown."
    )

    if prev_date_human:
        delta_header_label = (
            f"Downloads ({prev_date_human} → {latest_human})"
        )
    else:
        delta_header_label = "Downloads"

    if prev_date_human:
        table_footnote_text = (
            f"Change values are total downloads from {prev_date_human} to {latest_human} "
            "(the previous monthly snapshot to the latest). A dash (—) means no comparable prior value."
        )
    else:
        table_footnote_text = (
            "No prior monthly snapshot to compare against yet — change values will populate next run."
        )

    methodology_text = (
        "Numbers are aggregated lifetime totals since January 1, 2020, pulled monthly from "
        "ICPSR's PCMS APIs (curated datasets) and the openICPSR usage endpoint (self-published datasets). "
        "Curated entries report data and documentation downloads, unique users, and citing publications. "
        "Self-published entries report total downloads and total project-page views only — openICPSR "
        "does not expose a per-month breakdown. The dashboard is rebuilt automatically on the first of "
        "each month from the latest scrape."
    )

    page_title = f"NaNDA Usage Dashboard — {latest_human}"

    # --- HTML document ---
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(page_title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root {{
  /* NaNDA brand */
  --nanda-blue-dark: #01528a;
  --nanda-blue-light: #1499d6;
  --nanda-white: #ffffff;
  /* Semantic aliases */
  --bg: var(--nanda-white);
  --surface: var(--nanda-white);
  --text: #1a2c5b;
  --muted: #555555;
  --accent: var(--nanda-blue-light);
  --border: #d0d7de;
  --pos: #16a34a;
  --neg: #b42318;
  --row-hover: #eaf4fb;
  --focus: #ff8a00;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; overflow-x: hidden; }}
body {{
  font-family: 'Atkinson Hyperlegible', system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  margin: 0;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  overflow-x: hidden;
}}
.page {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.5rem clamp(1rem, 3vw, 2rem) 2rem;
}}
.skip-link {{
  position: absolute; left: -9999px; top: auto; width: 1px; height: 1px; overflow: hidden;
}}
.skip-link:focus {{
  position: static; width: auto; height: auto; padding: 0.5rem 1rem;
  background: var(--nanda-blue-dark); color: #fff; text-decoration: none; display: inline-block;
  margin: 0.5rem 0;
}}
.visually-hidden {{
  position: absolute !important;
  width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}}

a {{ color: var(--nanda-blue-dark); text-decoration: underline; text-underline-offset: 2px; }}
a:hover {{ color: var(--nanda-blue-dark); text-decoration-thickness: 2px; }}
a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible {{
  outline: 3px solid var(--focus);
  outline-offset: 2px;
  border-radius: 2px;
}}

header {{
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
  margin-bottom: 2rem;
}}
.header-logo {{
  display: flex;
  justify-content: center;
  width: 100%;
}}
.header-logo a {{
  display: inline-block;
  text-decoration: none;
  max-width: 100%;
}}
.header-logo .logo {{
  height: 140px;
  width: auto;
  max-width: 100%;
  display: block;
}}
.header-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem 1.5rem;
}}
.header-title h1 {{
  margin: 0;
  font-size: clamp(1.4rem, 2.5vw, 1.8rem);
  line-height: 1.2;
  color: var(--text);
}}
.header-title .tagline {{
  margin: 0.35rem 0 0;
  color: var(--muted);
  font-size: 0.95rem;
  max-width: 65ch;
}}
.updated {{ margin: 0; color: var(--muted); font-size: 0.9rem; }}
.updated time {{ font-weight: 700; color: var(--text); }}

section {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}}
section h2 {{
  margin: 0 0 1rem;
  font-size: 1.15rem;
  color: var(--text);
  font-weight: 700;
}}
section .definition {{
  margin: 0 0 1.25rem;
  padding: 0.85rem 1rem;
  background: #eaf4fb;
  border-left: 4px solid var(--nanda-blue-dark);
  border-radius: 4px;
  font-size: 0.92rem;
  color: var(--text);
}}
.definition strong {{ color: var(--text); font-weight: 700; }}

/* KPI cards */
.kpis {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
  padding: 0;
  background: transparent;
  box-shadow: none;
  margin-bottom: 1.5rem;
}}
.kpi {{
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 1.25rem 1.5rem;
  border-radius: 8px;
}}
.kpi dl {{ margin: 0; }}
.kpi dt {{
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
  font-weight: 700;
}}
.kpi-value {{
  margin: 0.35rem 0 0;
  font-size: 2rem;
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}}
.kpi-delta {{
  margin: 0.5rem 0 0;
  font-size: 0.85rem;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}}
.kpi-delta.delta-pos {{ color: var(--pos); }}
.kpi-delta.delta-neg {{ color: var(--neg); }}
.kpi-delta.muted {{ color: var(--muted); }}

/* Chart */
.chart-wrap {{
  position: relative;
  height: 320px;
  margin-top: 0.5rem;
}}
.chart-wrap canvas {{ max-width: 100%; }}

/* Filter row */
.filter-row {{
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  margin-bottom: 0.75rem;
}}
.filter-row label {{
  font-weight: 700;
  font-size: 0.95rem;
  color: var(--text);
}}
.filter-row input[type="search"] {{
  flex: 1 1 220px;
  min-width: 0;
  padding: 0.5rem 0.75rem;
  font: inherit;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: #fff;
  color: var(--text);
}}
.filter-row input[type="search"]:focus-visible {{
  border-color: var(--nanda-blue-dark);
}}
.filter-count {{
  margin: 0;
  font-size: 0.9rem;
  color: var(--muted);
}}

/* Tables */
.table-scroll {{ overflow-x: auto; }}
table.studies-table {{
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
  table-layout: fixed;
}}
table.studies-table th,
table.studies-table td {{
  text-align: left;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid #e6e8eb;
  vertical-align: top;
}}
table.studies-table tbody td {{
  font-size: 1rem;
  color: var(--text);
}}
table.studies-table th {{
  background: #f0f3f6;
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--text);
}}
table.studies-table th.num,
table.studies-table td.num {{
  text-align: right;
  font-variant-numeric: tabular-nums;
}}
table.studies-table col.col-num {{ width: 8.5rem; }}
table.studies-table col.col-num-narrow {{ width: 7rem; }}
table.studies-table .title-cell {{
  white-space: normal;
  overflow-wrap: anywhere;
  hyphens: auto;
  line-height: 1.4;
}}
table.studies-table .title-cell a {{
  text-decoration: underline;
  text-underline-offset: 2px;
}}
table.studies-table tbody tr:hover {{ background: var(--row-hover); }}
.muted {{ color: var(--muted); }}
.delta-pos {{ color: var(--pos); }}
.delta-neg {{ color: var(--neg); }}
/* Lift specificity above `table.studies-table tbody td` (0,1,3) so positive
   deltas actually render in the palette green inside table cells. */
table.studies-table tbody td.delta-pos {{ color: var(--pos); }}
table.studies-table tbody td.delta-neg {{ color: var(--neg); }}

button.sort-btn {{
  appearance: none;
  background: transparent;
  border: 0;
  padding: 0;
  margin: 0;
  font: inherit;
  font-weight: 700;
  color: inherit;
  cursor: pointer;
  text-align: inherit;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  width: 100%;
}}
table.studies-table th.num button.sort-btn {{
  justify-content: flex-end;
}}
button.sort-btn:hover {{ text-decoration: underline; text-underline-offset: 3px; }}
th[aria-sort="ascending"] button.sort-btn::after {{ content: "▲"; font-size: 0.75em; color: var(--nanda-blue-dark); }}
th[aria-sort="descending"] button.sort-btn::after {{ content: "▼"; font-size: 0.75em; color: var(--nanda-blue-dark); }}
th[aria-sort="none"] button.sort-btn::after {{ content: "↕"; font-size: 0.8em; color: var(--muted); opacity: 0.6; }}

.row-hidden {{ display: none; }}

.table-footnote {{
  margin: 0.6rem 0 0;
  font-size: 0.85rem;
  color: var(--muted);
}}

details {{
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.5rem 0.85rem;
  background: var(--nanda-white);
}}
details > summary {{
  cursor: pointer;
  font-weight: 700;
  color: var(--text);
}}
details[open] > summary {{ margin-bottom: 0.5rem; }}
details p {{ margin: 0.5rem 0 0; }}

details.section-accordion {{
  border: none;
  padding: 0;
  background: transparent;
}}
details.section-accordion > summary {{ cursor: pointer; }}
details.section-accordion > summary > h2 {{ display: inline; margin: 0; }}
details.section-accordion p {{ margin: revert; }}

footer {{
  border-top: 1px solid var(--border);
  margin-top: 1rem;
  padding: 1.5rem 0 0.5rem;
  color: var(--muted);
  font-size: 0.9rem;
}}
footer nav ul {{
  list-style: none;
  padding: 0;
  margin: 0 0 0.75rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.5rem;
}}
footer nav a {{ font-weight: 700; }}
footer p {{ margin: 0; }}

@media (max-width: 600px) {{
  header {{ gap: 1.25rem; }}
  .header-logo .logo {{ height: 80px; }}
  .header-row {{ gap: 0.5rem 1rem; }}
  .kpi {{ padding: 1rem 1.1rem; }}
  .kpi-value {{ font-size: 1.6rem; }}
  section {{ padding: 1.1rem; }}
  table.studies-table {{ font-size: 0.85rem; }}
  table.studies-table th,
  table.studies-table td {{ padding: 0.5rem 0.55rem; }}
}}
</style>
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<div class="page">
<header>
  <div class="header-logo">
    <a href="https://nanda.isr.umich.edu/" target="_blank" rel="noopener noreferrer">
      <img src="assets/nanda-logo.svg" alt="NaNDA — National Neighborhood Data Archive" class="logo" width="812" height="140">
    </a>
  </div>
  <div class="header-row">
    <div class="header-title">
      <h1>NaNDA Usage Dashboard</h1>
      <p class="tagline">The National Neighborhood Data Archive — monthly usage of our datasets on ICPSR and openICPSR.</p>
    </div>
    <p class="updated">Data through <time datetime="{latest_iso}">{latest_human}</time></p>
  </div>
</header>

<main id="main">

<section class="kpis" aria-label="Key metrics">
  <div class="kpi">
    <dl>
      <dt>Total downloads</dt>
      <dd class="kpi-value">{total_downloads:,}</dd>
      {kpi_delta_html(delta_total)}
    </dl>
  </div>
  <div class="kpi">
    <dl>
      <dt>Datasets tracked</dt>
      <dd class="kpi-value">{n_datasets}</dd>
      {kpi_delta_html(delta_n_datasets)}
    </dl>
  </div>
  <div class="kpi">
    <dl>
      <dt>Unique users (curated)</dt>
      <dd class="kpi-value">{unique_users_total:,}</dd>
      {kpi_delta_html(delta_unique_users)}
    </dl>
  </div>
</section>

<section aria-labelledby="chart-heading">
  <h2 id="chart-heading">Monthly downloads — aggregate (curated datasets)</h2>
  <div class="chart-wrap" role="img" aria-label="{html.escape(trend_summary)}">
    <canvas id="ts-chart"></canvas>
  </div>
  <table class="visually-hidden">
    <caption>Aggregate monthly downloads — chart data table</caption>
    <thead><tr><th scope="col">Month</th><th scope="col">Total downloads</th></tr></thead>
    <tbody>
{chart_data_rows}
    </tbody>
  </table>
</section>

<section aria-labelledby="curated-heading">
  <details class="section-accordion" open>
  <summary><h2 id="curated-heading">Curated NaNDA datasets ({curated_count})</h2></summary>
  <p class="definition" id="curated-def"><strong>Curated:</strong> {html.escape(curated_def)}</p>
  <div class="filter-row">
    <label for="filter-curated">Filter</label>
    <input type="search" id="filter-curated" data-target="curated-table" data-count="filter-curated-count" placeholder="Search by title or study ID" autocomplete="off" aria-describedby="curated-def filter-curated-count">
    <p class="filter-count" id="filter-curated-count" aria-live="polite" aria-atomic="true">Showing {curated_count} of {curated_count} curated studies</p>
  </div>
  <div class="table-scroll">
  <table id="curated-table" class="studies-table" aria-describedby="curated-def">
    <caption class="visually-hidden">Curated NaNDA datasets, sortable by column.</caption>
    <colgroup>
      <col>
      <col class="col-num">
      <col class="col-num">
      <col class="col-num-narrow">
      <col class="col-num-narrow">
    </colgroup>
    <thead>
      <tr>
        <th scope="col" aria-sort="none"><button type="button" class="sort-btn" data-key="title" data-type="text">Title</button></th>
        <th scope="col" class="num" aria-sort="descending"><button type="button" class="sort-btn" data-key="total" data-type="num">Total downloads</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="delta" data-type="num">{html.escape(delta_header_label)}</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="users" data-type="num">Unique users</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="pubs" data-type="num">Publications</button></th>
      </tr>
    </thead>
    <tbody>
{render_curated_tbody()}
    </tbody>
  </table>
  </div>
  <p class="table-footnote">{html.escape(table_footnote_text)}</p>
  </details>
</section>

<section aria-labelledby="self-heading">
  <details class="section-accordion" open>
  <summary><h2 id="self-heading">Self-published NaNDA datasets ({self_count})</h2></summary>
  <p class="definition" id="self-def"><strong>Self-published:</strong> {html.escape(self_def)}</p>
  <div class="filter-row">
    <label for="filter-self">Filter</label>
    <input type="search" id="filter-self" data-target="self-table" data-count="filter-self-count" placeholder="Search by title or study ID" autocomplete="off" aria-describedby="self-def filter-self-count">
    <p class="filter-count" id="filter-self-count" aria-live="polite" aria-atomic="true">Showing {self_count} of {self_count} self-published studies</p>
  </div>
  <div class="table-scroll">
  <table id="self-table" class="studies-table" aria-describedby="self-def">
    <caption class="visually-hidden">Self-published NaNDA datasets, sortable by column.</caption>
    <colgroup>
      <col>
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
    </colgroup>
    <thead>
      <tr>
        <th scope="col" aria-sort="none"><button type="button" class="sort-btn" data-key="title" data-type="text">Title</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="views" data-type="num">Total views</button></th>
        <th scope="col" class="num" aria-sort="descending"><button type="button" class="sort-btn" data-key="total" data-type="num">Total downloads</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="delta" data-type="num">{html.escape(delta_header_label)}</button></th>
      </tr>
    </thead>
    <tbody>
{render_openicpsr_tbody(self_rows)}
    </tbody>
  </table>
  </div>
  <p class="table-footnote">{html.escape(table_footnote_text)}</p>
  </details>
</section>

<section aria-labelledby="unpublished-heading">
  <details class="section-accordion">
  <summary><h2 id="unpublished-heading">Unpublished NaNDA datasets ({unpublished_count})</h2></summary>
  <p class="definition" id="unpublished-def"><strong>Unpublished:</strong> {html.escape(unpublished_def)}</p>
  <div class="filter-row">
    <label for="filter-unpublished">Filter</label>
    <input type="search" id="filter-unpublished" data-target="unpublished-table" data-count="filter-unpublished-count" placeholder="Search by title or study ID" autocomplete="off" aria-describedby="unpublished-def filter-unpublished-count">
    <p class="filter-count" id="filter-unpublished-count" aria-live="polite" aria-atomic="true">Showing {unpublished_count} of {unpublished_count} unpublished studies</p>
  </div>
  <div class="table-scroll">
  <table id="unpublished-table" class="studies-table" aria-describedby="unpublished-def">
    <caption class="visually-hidden">Unpublished NaNDA datasets, sortable by column.</caption>
    <colgroup>
      <col>
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
    </colgroup>
    <thead>
      <tr>
        <th scope="col" aria-sort="none"><button type="button" class="sort-btn" data-key="title" data-type="text">Title</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="views" data-type="num">Total views</button></th>
        <th scope="col" class="num" aria-sort="descending"><button type="button" class="sort-btn" data-key="total" data-type="num">Total downloads</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="delta" data-type="num">{html.escape(delta_header_label)}</button></th>
      </tr>
    </thead>
    <tbody>
{render_openicpsr_tbody(unpublished_rows)}
    </tbody>
  </table>
  </div>
  <p class="table-footnote">{html.escape(table_footnote_text)}</p>
  </details>
</section>

<section aria-labelledby="methodology-heading">
  <h2 id="methodology-heading">How this is calculated</h2>
  <details>
    <summary>Show methodology</summary>
    <p>{html.escape(methodology_text)}</p>
    <p>Source code, raw CSVs, and the full schema are on <a href="{html.escape(GITHUB_REPO)}">the dashboard's GitHub repository</a>.</p>
  </details>
</section>

</main>

<footer class="page-footer">
  <nav aria-label="Trust links">
    <ul>
      <li><a href="{html.escape(NANDA_HOMEPAGE)}">NaNDA homepage</a></li>
      <li><a href="{html.escape(GITHUB_REPO)}">Dashboard source code on GitHub</a></li>
      <li><a href="#methodology-heading">How this is calculated</a></li>
    </ul>
  </nav>
  <p>Data through <time datetime="{latest_iso}">{latest_human}</time>.</p>
</footer>

</div>

<script>
// --- Time-series chart ---
const tsLabels = {json.dumps(ts_labels)};
const tsValues = {json.dumps(ts_values)};
new Chart(document.getElementById("ts-chart"), {{
  type: "line",
  data: {{
    labels: tsLabels,
    datasets: [{{
      label: "Downloads",
      data: tsValues,
      borderColor: "#1499d6",
      backgroundColor: "rgba(20, 153, 214, 0.15)",
      borderWidth: 2,
      fill: true,
      tension: 0.25,
      pointRadius: 2,
      pointBackgroundColor: "#1499d6",
      pointBorderColor: "#1499d6",
    }}],
  }},
  options: {{
    maintainAspectRatio: false,
    animation: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: (ctx) => ctx.parsed.y.toLocaleString() + " downloads",
        }},
      }},
    }},
    scales: {{
      y: {{
        beginAtZero: true,
        ticks: {{ callback: v => v.toLocaleString(), color: "#1a2c5b" }},
        title: {{ display: true, text: "Downloads per month", color: "#1a2c5b", font: {{ size: 13, weight: "700" }} }},
        grid: {{ color: "rgba(26, 26, 26, 0.08)" }},
      }},
      x: {{
        ticks: {{ maxRotation: 45, autoSkip: true, maxTicksLimit: 16, color: "#1a2c5b" }},
        grid: {{ color: "rgba(26, 26, 26, 0.08)" }},
      }},
    }},
  }},
}});

// --- Sortable + filterable tables ---
(function() {{
  document.querySelectorAll("table.studies-table").forEach(function(table) {{
    const tbody = table.tBodies[0];
    const headRow = table.tHead.rows[0];
    const ths = Array.from(headRow.cells);

    function sortBy(colIdx, asc, type) {{
      const rows = Array.from(tbody.rows);
      rows.sort(function(a, b) {{
        const av = a.cells[colIdx].getAttribute("data-sort");
        const bv = b.cells[colIdx].getAttribute("data-sort");
        if (type === "num") {{
          const aEmpty = (av === null || av === "");
          const bEmpty = (bv === null || bv === "");
          if (aEmpty && bEmpty) return 0;
          if (aEmpty) return 1;
          if (bEmpty) return -1;
          const an = parseFloat(av), bn = parseFloat(bv);
          return asc ? an - bn : bn - an;
        }}
        const at = (av === null || av === "") ? a.cells[colIdx].textContent.trim() : av;
        const bt = (bv === null || bv === "") ? b.cells[colIdx].textContent.trim() : bv;
        return asc ? at.localeCompare(bt) : bt.localeCompare(at);
      }});
      rows.forEach(r => tbody.appendChild(r));
    }}

    ths.forEach(function(th, i) {{
      const btn = th.querySelector("button.sort-btn");
      if (!btn) return;
      btn.addEventListener("click", function() {{
        const current = th.getAttribute("aria-sort");
        const asc = current !== "ascending";
        ths.forEach(x => x.setAttribute("aria-sort", "none"));
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortBy(i, asc, btn.getAttribute("data-type") || "text");
      }});
      // Apply initial sort if header marked as descending/ascending in HTML
      if (th.getAttribute("aria-sort") === "descending") {{
        sortBy(i, false, btn.getAttribute("data-type") || "text");
      }} else if (th.getAttribute("aria-sort") === "ascending") {{
        sortBy(i, true, btn.getAttribute("data-type") || "text");
      }}
    }});
  }});

  // --- Filter inputs ---
  document.querySelectorAll('input[type="search"][data-target]').forEach(function(input) {{
    const table = document.getElementById(input.getAttribute("data-target"));
    const countEl = document.getElementById(input.getAttribute("data-count"));
    if (!table || !countEl) return;
    const baseCount = table.tBodies[0].rows.length;
    const nounByTable = {{
      "curated-table": "curated studies",
      "self-table": "self-published studies",
      "unpublished-table": "unpublished studies",
    }};
    const noun = nounByTable[table.id] || "studies";

    input.addEventListener("input", function() {{
      const q = input.value.trim().toLowerCase();
      let visible = 0;
      Array.from(table.tBodies[0].rows).forEach(function(row) {{
        const id = (row.dataset.studyId || "").toLowerCase();
        const title = row.cells[0].textContent.toLowerCase();
        const match = q === "" || id.includes(q) || title.includes(q);
        row.classList.toggle("row-hidden", !match);
        if (match) visible++;
      }});
      countEl.textContent = q === ""
        ? "Showing " + baseCount + " of " + baseCount + " " + noun
        : "Showing " + visible + " of " + baseCount + " " + noun + " matching \\u201C" + input.value + "\\u201D";
    }});
  }});
}})();
</script>
</body>
</html>
"""

    out_path = OUTPUT_DIR / "index.html"
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html_doc):,} bytes)")
    print(f"  KPIs: {total_downloads:,} downloads, {n_datasets} datasets, {unique_users_total:,} users")
    print(f"  Time-series points: {len(ts_labels)}")
    print(
        f"  Curated rows: {len(curated_rows)} | "
        f"Self-published rows: {len(self_rows)} | "
        f"Unpublished rows: {len(unpublished_rows)}"
    )


if __name__ == "__main__":
    main()
