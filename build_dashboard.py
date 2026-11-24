#!/usr/bin/env python3
"""
Build a single-file static dashboard summarizing the latest NaNDA usage
scrape. Reads the three artifacts produced by the scraper and writes a
self-contained `docs/index.html` with inline CSS and Chart.js from
CDN.

Inputs:
  data/nanda_usage_stats_latest.csv
  data/nanda_usage_stats_YYYY-MM-DD.csv  (most recent strict-pattern file
                                          before today's, for Δ computation)
  data/nanda_usage_timeseries_YYYY-MM-DD.csv
  data/nanda_download_history.csv        (both read through build_history.py,
                                          which rebuilds the month-by-month
                                          history behind curated download
                                          totals, their Δ, and the trend chart)
  inventory.csv                          (archive routing: ICPSR vs openICPSR;
                                          deposit_via for the one-time two-source
                                          notice; and, since 2026-11-24, the title,
                                          version, doi, and url each row displays,
                                          so a correction in the list shows at the
                                          next build without a scrape)
  docs/assets/nanda-logo.svg             (NaNDA wordmark, served alongside HTML)

Output:
  docs/index.html

Lives in `docs/` because GitHub Pages only allows publishing from `/` or
`/docs`, not arbitrary subfolders. To publish: Settings, Pages, branch
main, folder /docs.
"""

import html
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from build_history import apply_history_totals, build_history, preserved_downloads
from generate_delta import first_both_sources_notice

DATA_DIR = Path("data")
OUTPUT_DIR = Path("docs")
LATEST_CSV  = DATA_DIR / "nanda_usage_stats_latest.csv"
INVENTORY_CSV = Path("inventory.csv")
DATED_RE = re.compile(r"^nanda_usage_stats_(\d{4}-\d{2}-\d{2})\.csv$")

# Same prefix nanda_usage_scraper.load_inventory strips, so inventory titles match the
# short form the snapshots carry. Kept here rather than imported: importing the scraper
# builds its study list and pulls in cloudscraper.
NANDA_PREFIX = "National Neighborhood Data Archive (NaNDA): "
# Inventory column -> snapshot column it replaces at build time.
INVENTORY_DISPLAY_FIELDS = {"title": "dataset_title", "doi": "doi", "url": "url", "version": "version"}

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


def apply_inventory_details(current: pd.DataFrame, inventory) -> pd.DataFrame:
    """Join archive and publication status from the inventory, and take each row's
    title, version, doi, and url from the inventory where it has them.

    The inventory (nanda-inventory's deposit_status.csv, exported weekly) is the dataset
    list, so a correction there should show on the dashboard at the next build, without
    waiting for a scrape. The snapshot's own values are used only for a study the
    inventory does not list, or for a cell the inventory leaves blank. Inventory's
    `status` is renamed `pub_status` on merge: snapshots dated before 2026-08 call the
    scrape-outcome column `status`, and the rename keeps the two from colliding.
    Row order and count are unchanged."""
    out = current.copy()
    if inventory is None:
        out["archive"] = "ICPSR"  # fallback; should never hit in CI
        out["pub_status"] = "published"
        out["version"] = pd.NA
        return out
    cols = ["study_id", "archive", "status"] + [c for c in INVENTORY_DISPLAY_FIELDS if c in inventory.columns]
    inv = inventory[cols].rename(columns={"status": "pub_status"})
    inv = inv.rename(columns={c: f"_inv_{c}" for c in INVENTORY_DISPLAY_FIELDS if c in inv.columns})
    out = out.merge(inv, on="study_id", how="left")
    if "_inv_title" in out.columns:
        out["_inv_title"] = out["_inv_title"].map(
            lambda t: t[len(NANDA_PREFIX):] if isinstance(t, str) and t.startswith(NANDA_PREFIX) else t)
    for inv_col, snap_col in INVENTORY_DISPLAY_FIELDS.items():
        src = f"_inv_{inv_col}"
        if src not in out.columns:
            continue
        if snap_col not in out.columns:
            out[snap_col] = pd.NA
        has_value = out[src].notna() & (out[src].astype(str).str.strip() != "")
        out.loc[has_value, snap_col] = out.loc[has_value, src]
        out = out.drop(columns=[src])
    if "version" not in out.columns:
        out["version"] = pd.NA
    return out


def main() -> None:
    if not LATEST_CSV.exists():
        print(f"Missing {LATEST_CSV}. Run the scraper first.")
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

    # --- Download totals from the saved month-by-month history ---
    # ICPSR keeps a rolling three-year window and trims its oldest months in
    # batches, so the totals it reports shrink at every trim. Any study with
    # history rows takes its total from the history sum (build_history.py);
    # everything else keeps its reported total. Unique users can't be
    # rebuilt this way and stay as ICPSR reports them.
    history = build_history(DATA_DIR)
    current = apply_history_totals(current, history)
    preserved = preserved_downloads(history, current["study_id"])

    # --- Archive routing, publication status, and display fields from inventory ---
    inventory = pd.read_csv(INVENTORY_CSV) if INVENTORY_CSV.exists() else None
    current = apply_inventory_details(current, inventory)

    # Self-published rows carry both usage sources since 2026-11. Older
    # snapshots lack the two columns; treat them as missing.
    for col in ("earlier_version_downloads", "current_deposit_downloads"):
        if col not in current.columns:
            current[col] = pd.NA

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
        # Same treatment as of the previous snapshot, so the Δ compares
        # like with like and an ICPSR trim doesn't read as lost downloads.
        prev_df = apply_history_totals(
            pd.read_csv(prev_path), build_history(DATA_DIR, cutoff=prev_date_iso)
        )
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

    # --- Time-series aggregate (from the history, so months ICPSR has
    # dropped stay on the chart) ---
    if not history.empty:
        monthly = (history.groupby(["year", "month"], as_index=False)["total_downloads"]
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
        version = r.get("version")
        version_str = "" if pd.isna(version) else str(version)
        archive = r.get("archive") or "ICPSR"
        pub_status = r.get("pub_status") or "published"
        table_rows.append({
            "study_id":   int(r["study_id"]),
            "title":      title_str,
            "doi":        doi_str,
            "url":        url_str,
            "version":    version_str,
            "archive":    archive,
            "pub_status": pub_status,
            "total":      int(r["total_downloads"]) if pd.notna(r["total_downloads"]) else 0,
            "delta":      None if pd.isna(r["delta"]) else int(r["delta"]),
            "users":      None if pd.isna(r.get("unique_users")) else int(r["unique_users"]),
            "pubs":       None if pd.isna(r.get("publications")) else int(r["publications"]),
            "views":      None if pd.isna(r.get("total_views")) else int(r["total_views"]),
            "earlier":    None if pd.isna(r.get("earlier_version_downloads")) else int(r["earlier_version_downloads"]),
            "current":    None if pd.isna(r.get("current_deposit_downloads")) else int(r["current_deposit_downloads"]),
        })

    curated_rows = [r for r in table_rows if r["archive"] == "ICPSR"]
    self_rows = [r for r in table_rows
                 if r["archive"] == "openICPSR" and r["pub_status"] != "unpublished"]
    unpublished_rows = [r for r in table_rows if r["pub_status"] == "unpublished"]

    # --- Render helpers ---
    def title_link(row):
        title_safe = html.escape(row["title"])
        # The version comes from the inventory and shows after the title, so a version
        # correction there is visible here at the next build.
        version = f' <span class="muted version">{html.escape(row["version"])}</span>' if row["version"] else ""
        if row["doi"]:
            href = "https://doi.org/" + row["doi"]
            return f'<a href="{html.escape(href)}">{title_safe}</a>{version}'
        if row["url"]:
            return f'<a href="{html.escape(row["url"])}">{title_safe}</a>{version}'
        return title_safe + version

    def delta_cell(row):
        if row["delta"] is None:
            return '<td class="num" data-sort=""><span class="muted">–</span></td>'
        cls = ""
        title_attr = ""
        if row["delta"] > 0:
            cls = " delta-pos"
        elif row["delta"] < 0:
            cls = " delta-neg"
            # Cumulative counts only fall when the source revises its
            # history (or a scrape failed): say so instead of implying
            # downloads were lost.
            title_attr = (' title="Decrease reflects a revision of ICPSR&#39;s '
                          'historical data or a scrape error, not lost downloads"')
        return (
            f'<td class="num{cls}" data-sort="{row["delta"]}"{title_attr}>'
            f'{fmt_signed(row["delta"])}'
            f'</td>'
        )

    def num_cell(value):
        if value is None:
            return '<td class="num" data-sort=""><span class="muted">–</span></td>'
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

    def source_cell(value, other):
        # A dataset with nothing in one source shows 0, not a dash: the
        # source was asked and had nothing to add. Only when neither source
        # column exists (a snapshot from before 2026-12) is the value
        # unknown, and then a dash with a text alternative is shown.
        if value is None and other is None:
            return ('<td class="num" data-sort=""><span class="muted" aria-hidden="true">–</span>'
                    '<span class="visually-hidden">not reported</span></td>')
        return num_cell(0 if value is None else value)

    def render_openicpsr_tbody(rows):
        out = []
        for row in rows:
            out.append(
                f"<tr data-study-id=\"{row['study_id']}\">"
                f"<td class=\"title-cell\">{title_link(row)}</td>"
                f"{num_cell(row['views'])}"
                f"{source_cell(row['earlier'], row['current'])}"
                f"{source_cell(row['current'], row['earlier'])}"
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
            return '<dd class="kpi-delta muted">No prior snapshot</dd>'
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
        "Datasets deposited through ICPSR's self-deposit system (formerly openICPSR). "
        "Self-published releases skip the full curation pipeline, so usage reporting is limited "
        "to total downloads and project-page views: no per-month breakdown, unique-user count, "
        "or publication tracking."
    )
    # One note per table (not a marker on every row) tying the two source
    # columns to the total. Attached to the table with aria-describedby.
    sources_note = (
        "Total downloads add two numbers: downloads of the earlier version on openICPSR, "
        "and downloads of the current deposit in ICPSR's self-deposit system. "
        "A small number of downloads may be counted in both."
    )
    unpublished_def = (
        "Datasets in NaNDA's inventory marked status=unpublished: openICPSR deposits "
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
            "(the previous monthly snapshot to the latest). A dash (–) means no comparable prior value."
        )
    else:
        table_footnote_text = (
            "No prior monthly snapshot to compare against yet. Change values will populate next run."
        )

    # --- Source-revision notice ---
    # Download totals keep the months ICPSR trims (see build_history.py), but
    # unique users only cover the window ICPSR currently serves, so they can
    # still fall at a trim; a scrape error can pull either number down.
    # Annotate the dip; never hide it.
    delta_report_url = ("https://github.com/The-National-Neighborhood-Data-Archive/"
                        "usage-metrics/blob/main/data/delta_latest.md")
    if ((delta_total is not None and delta_total < 0)
            or (delta_unique_users is not None and delta_unique_users < 0)):
        revision_notice = f"""
<aside class="notice" aria-label="Data revision notice">
  <p><strong>Why did a number drop?</strong> Download totals keep months ICPSR has removed,
  but unique users only cover the window ICPSR currently reports, so they can fall when ICPSR
  trims its oldest months. A drop can also come from a scrape error. The
  <a href="{delta_report_url}">latest delta report</a> lists the affected datasets.</p>
</aside>"""
    else:
        revision_notice = ""

    # --- One-time two-source notice ---
    # Shown only for the first build whose snapshot carries both usage
    # sources for self-published datasets while the previous snapshot does
    # not. The headline and per-row changes jump by downloads that were
    # always there; say so. Independent of the trim notice above; both can
    # show in the same month.
    both_sources_text = first_both_sources_notice(current, prev_df, inventory)
    if both_sources_text:
        revision_notice = f"""
<aside class="notice" aria-label="New usage source notice">
  <p><strong>New usage source.</strong> {html.escape(both_sources_text)} The two parts are the
  Earlier version and Current deposit columns of the self-published and unpublished tables.</p>
</aside>""" + revision_notice

    history_start = f", which begins in {fmt_human_month(ts_labels[0])}" if ts_labels else ""
    methodology_text = (
        "Numbers are pulled monthly from ICPSR's PCMS APIs (curated datasets) and, for "
        "self-published datasets, from two sources that are added together: the openICPSR usage "
        "endpoint, which holds downloads of the earlier version of each dataset, and the "
        "usage-statistics endpoint of ICPSR's self-deposit system, which holds downloads of the "
        "current deposit. ICPSR keeps a rolling three-year window of "
        "download history and periodically removes older months from its reporting. So those "
        "downloads stay counted, this dashboard saves every monthly scrape and totals curated "
        f"downloads from that saved month-by-month history{history_start}. "
        f"Of the {total_downloads:,} downloads shown, {preserved:,} come from months ICPSR no "
        "longer reports. Unique users can't be added up across months, so that figure covers "
        "only the window ICPSR currently serves (roughly the past three years). Curated entries "
        "report data and documentation downloads, unique users, and citing publications. "
        "Self-published entries report total downloads and total project-page views only, "
        "because neither source exposes a per-month breakdown; they appear as ICPSR reports "
        "them, and a small number of downloads may be counted in both sources. The dashboard "
        "is rebuilt automatically on the first of each month from the latest scrape."
    )

    page_title = f"NaNDA Usage Dashboard: {latest_human}"

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
.notice {{
  margin: 0 0 1.5rem;
  padding: 0.85rem 1rem;
  background: #fff7e6;
  border: 1px solid var(--border);
  border-left: 4px solid #b45309;
  border-radius: 8px;
  font-size: 0.95rem;
  color: var(--text);
}}
.notice p {{ margin: 0; }}
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
/* Six-column tables (self-published, unpublished): narrower number columns
   and a wider minimum so the title column keeps room to read. */
table.studies-table.six-col {{ min-width: 62rem; }}
table.studies-table.six-col col.col-num {{ width: 7rem; }}
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
table.studies-table .title-cell .version {{
  font-size: 0.85em;
  white-space: nowrap;
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
      <img src="assets/nanda-logo.svg" alt="NaNDA: National Neighborhood Data Archive" class="logo" width="812" height="140">
    </a>
  </div>
  <div class="header-row">
    <div class="header-title">
      <h1>NaNDA Usage Dashboard</h1>
      <p class="tagline">The National Neighborhood Data Archive: monthly usage of our datasets at ICPSR.</p>
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
      <dt>Unique users (curated, past 3 years)</dt>
      <dd class="kpi-value">{unique_users_total:,}</dd>
      {kpi_delta_html(delta_unique_users)}
    </dl>
  </div>
</section>
{revision_notice}

<section aria-labelledby="chart-heading">
  <h2 id="chart-heading">Monthly downloads, all curated datasets</h2>
  <div class="chart-wrap" role="img" aria-label="{html.escape(trend_summary)}">
    <canvas id="ts-chart"></canvas>
  </div>
  <table class="visually-hidden">
    <caption>Aggregate monthly downloads: chart data table</caption>
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
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="users" data-type="num">Unique users (past 3 years)</button></th>
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
  <p class="definition" id="self-sources-note"><strong>Two sources:</strong> {html.escape(sources_note)}</p>
  <div class="filter-row">
    <label for="filter-self">Filter</label>
    <input type="search" id="filter-self" data-target="self-table" data-count="filter-self-count" placeholder="Search by title or study ID" autocomplete="off" aria-describedby="self-def filter-self-count">
    <p class="filter-count" id="filter-self-count" aria-live="polite" aria-atomic="true">Showing {self_count} of {self_count} self-published studies</p>
  </div>
  <div class="table-scroll">
  <table id="self-table" class="studies-table six-col" aria-describedby="self-def self-sources-note">
    <caption class="visually-hidden">Self-published NaNDA datasets, sortable by column.</caption>
    <colgroup>
      <col>
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
    </colgroup>
    <thead>
      <tr>
        <th scope="col" aria-sort="none"><button type="button" class="sort-btn" data-key="title" data-type="text">Title</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="views" data-type="num">Total views</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="earlier" data-type="num">Earlier version (openICPSR)</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="current" data-type="num">Current deposit</button></th>
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
  <p class="definition" id="unpublished-sources-note"><strong>Two sources:</strong> {html.escape(sources_note)}</p>
  <div class="filter-row">
    <label for="filter-unpublished">Filter</label>
    <input type="search" id="filter-unpublished" data-target="unpublished-table" data-count="filter-unpublished-count" placeholder="Search by title or study ID" autocomplete="off" aria-describedby="unpublished-def filter-unpublished-count">
    <p class="filter-count" id="filter-unpublished-count" aria-live="polite" aria-atomic="true">Showing {unpublished_count} of {unpublished_count} unpublished studies</p>
  </div>
  <div class="table-scroll">
  <table id="unpublished-table" class="studies-table six-col" aria-describedby="unpublished-def unpublished-sources-note">
    <caption class="visually-hidden">Unpublished NaNDA datasets, sortable by column.</caption>
    <colgroup>
      <col>
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
      <col class="col-num">
    </colgroup>
    <thead>
      <tr>
        <th scope="col" aria-sort="none"><button type="button" class="sort-btn" data-key="title" data-type="text">Title</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="views" data-type="num">Total views</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="earlier" data-type="num">Earlier version (openICPSR)</button></th>
        <th scope="col" class="num" aria-sort="none"><button type="button" class="sort-btn" data-key="current" data-type="num">Current deposit</button></th>
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
    print(f"  Downloads preserved from months ICPSR no longer reports: {preserved:,}")
    print(f"  Time-series points: {len(ts_labels)}")
    print(
        f"  Curated rows: {len(curated_rows)} | "
        f"Self-published rows: {len(self_rows)} | "
        f"Unpublished rows: {len(unpublished_rows)}"
    )


if __name__ == "__main__":
    main()
