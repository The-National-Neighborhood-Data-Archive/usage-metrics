#!/usr/bin/env python3
"""
Build a single-file static dashboard summarizing the latest NaNDA usage
scrape. Reads the three artifacts produced by the scraper and writes a
self-contained `dashboard/index.html` with inline CSS and Chart.js from
CDN.

Inputs:
  data/nanda_usage_stats_latest.csv
  data/nanda_usage_timeseries_latest.csv
  data/nanda_usage_stats_YYYY-MM-DD.csv  (most recent strict-pattern file
                                          before today's, for Δ computation)

Output:
  dashboard/index.html

Run after the scraper. Can be flipped to GitHub Pages later by enabling
Pages on the `dashboard/` folder in repo settings; no code change needed.
"""

import html
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
OUTPUT_DIR = Path("dashboard")
LATEST_CSV  = DATA_DIR / "nanda_usage_stats_latest.csv"
TIMESERIES_CSV = DATA_DIR / "nanda_usage_timeseries_latest.csv"
DATED_RE = re.compile(r"^nanda_usage_stats_(\d{4}-\d{2}-\d{2})\.csv$")


def find_previous_snapshot():
    files = []
    for f in DATA_DIR.glob("nanda_usage_stats_*.csv"):
        m = DATED_RE.match(f.name)
        if m:
            files.append((m.group(1), f))
    files.sort(key=lambda x: x[0])
    if len(files) < 2:
        return None
    return files[-2]


def fmt_int(n):
    if pd.isna(n):
        return ""
    return f"{int(n):,}"


def fmt_signed(n):
    if pd.isna(n):
        return ""
    sign = "+" if n > 0 else ""
    return f"{sign}{int(n):,}"


def main() -> None:
    if not LATEST_CSV.exists():
        print(f"Missing {LATEST_CSV} — run the scraper first")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    today_human = datetime.now().strftime("%B %d, %Y")

    current = pd.read_csv(LATEST_CSV)

    # --- Δ computation against most recent prior snapshot ---
    prev = find_previous_snapshot()
    if prev is None:
        prev_date = None
        prev_df = None
        delta_total = None
    else:
        prev_date, prev_path = prev
        prev_df = pd.read_csv(prev_path)
        delta_total = int(current["total_downloads"].sum() - prev_df["total_downloads"].sum())

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
    # unique_users is curated-only, NaN for openICPSR rows
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

    # --- Studies table rows (all 103, sortable client-side) ---
    table_rows = []
    for _, r in merged.iterrows():
        title = r.get("dataset_title")
        title_str = "" if pd.isna(title) else str(title)
        title_short = title_str if len(title_str) <= 90 else title_str[:89].rstrip() + "…"
        table_rows.append({
            "study_id":   int(r["study_id"]),
            "title":      title_str,
            "title_short": title_short,
            "total":      int(r["total_downloads"]) if pd.notna(r["total_downloads"]) else 0,
            "delta":      None if pd.isna(r["delta"]) else int(r["delta"]),
            "users":      None if pd.isna(r["unique_users"]) else int(r["unique_users"]),
            "pubs":       None if pd.isna(r.get("publications")) else int(r["publications"]),
        })

    # --- Render HTML ---
    delta_kpi_html = (
        f"<small>{fmt_signed(delta_total)} since {prev_date}</small>"
        if prev_date is not None else ""
    )
    delta_th = f"Δ since {prev_date}" if prev_date else "Δ"

    # Build table tbody server-side; client JS just handles sort
    tbody_rows = []
    for row in table_rows:
        delta_cell = "" if row["delta"] is None else fmt_signed(row["delta"])
        delta_class = ""
        if row["delta"] is not None:
            if row["delta"] > 0: delta_class = "delta-pos"
            elif row["delta"] < 0: delta_class = "delta-neg"
        users_cell = "" if row["users"] is None else f"{row['users']:,}"
        pubs_cell  = "" if row["pubs"]  is None else f"{row['pubs']:,}"
        tbody_rows.append(
            f"<tr>"
            f"<td>{row['study_id']}</td>"
            f"<td title=\"{html.escape(row['title'])}\">{html.escape(row['title_short'])}</td>"
            f"<td class=\"num\" data-sort=\"{row['total']}\">{row['total']:,}</td>"
            f"<td class=\"num {delta_class}\" data-sort=\"{row['delta'] if row['delta'] is not None else ''}\">{delta_cell}</td>"
            f"<td class=\"num\" data-sort=\"{row['users'] if row['users'] is not None else ''}\">{users_cell}</td>"
            f"<td class=\"num\" data-sort=\"{row['pubs']  if row['pubs']  is not None else ''}\">{pubs_cell}</td>"
            f"</tr>"
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NaNDA Usage Dashboard — {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
* {{ box-sizing: border-box; }}
body {{
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  margin: 0; padding: 2rem;
  background: #f7f7f8; color: #222;
  max-width: 1200px; margin: 0 auto;
}}
h1 {{ margin: 0 0 0.25rem; font-size: 1.6rem; }}
header p {{ margin: 0 0 1.5rem; color: #666; }}
section {{ background: #fff; border-radius: 8px; padding: 1.25rem 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
section h2 {{ margin: 0 0 1rem; font-size: 1.1rem; color: #333; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; padding: 0; background: transparent; box-shadow: none; }}
.kpi {{ background: #fff; padding: 1.25rem 1.5rem; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
.kpi h2 {{ margin: 0; font-size: 2rem; font-weight: 700; color: #1a1a1a; }}
.kpi p {{ margin: 0.25rem 0 0; color: #666; font-size: 0.9rem; }}
.kpi small {{ display: block; margin-top: 0.5rem; color: #888; font-size: 0.8rem; }}
.chart-wrap {{ position: relative; height: 320px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
th, td {{ text-align: left; padding: 0.55rem 0.75rem; border-bottom: 1px solid #eee; }}
th {{ cursor: pointer; user-select: none; background: #fafafa; font-weight: 600; }}
th:hover {{ background: #f0f0f0; }}
th.sort-asc::after  {{ content: " ▲"; color: #888; }}
th.sort-desc::after {{ content: " ▼"; color: #888; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.delta-pos {{ color: #1a7f37; }}
td.delta-neg {{ color: #cf222e; }}
tbody tr:hover {{ background: #fafbfc; }}
footer {{ text-align: center; color: #888; font-size: 0.85rem; padding: 1rem 0; }}
</style>
</head>
<body>
<header>
  <h1>NaNDA Usage Dashboard</h1>
  <p>Auto-generated from monthly ICPSR / openICPSR scrape — {today_human}</p>
</header>

<section class="kpis">
  <div class="kpi">
    <h2>{total_downloads:,}</h2>
    <p>Total downloads</p>
    {delta_kpi_html}
  </div>
  <div class="kpi">
    <h2>{n_datasets}</h2>
    <p>Datasets tracked</p>
  </div>
  <div class="kpi">
    <h2>{unique_users_total:,}</h2>
    <p>Unique users (curated)</p>
  </div>
</section>

<section>
  <h2>Monthly downloads — aggregate (curated only)</h2>
  <div class="chart-wrap"><canvas id="ts-chart"></canvas></div>
</section>

<section>
  <h2>All studies</h2>
  <table id="studies-table">
    <thead>
      <tr>
        <th data-key="study_id">Study ID</th>
        <th data-key="title">Title</th>
        <th data-key="total" class="num">Total downloads</th>
        <th data-key="delta" class="num">{html.escape(delta_th)}</th>
        <th data-key="users" class="num">Unique users</th>
        <th data-key="pubs"  class="num">Publications</th>
      </tr>
    </thead>
    <tbody>
{chr(10).join("      " + r for r in tbody_rows)}
    </tbody>
  </table>
</section>

<footer>Last updated {today_human}</footer>

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
      borderColor: "#1f6feb",
      backgroundColor: "rgba(31, 111, 235, 0.1)",
      fill: true,
      tension: 0.25,
      pointRadius: 2,
    }}],
  }},
  options: {{
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{ beginAtZero: true, ticks: {{ callback: v => v.toLocaleString() }} }},
      x: {{ ticks: {{ maxRotation: 45, autoSkip: true, maxTicksLimit: 16 }} }},
    }},
  }},
}});

// --- Click-to-sort table (vanilla JS) ---
(function() {{
  const table = document.getElementById("studies-table");
  const tbody = table.tBodies[0];
  const ths = Array.from(table.tHead.rows[0].cells);

  function sortBy(colIdx, asc) {{
    const rows = Array.from(tbody.rows);
    rows.sort((a, b) => {{
      const av = a.cells[colIdx].dataset.sort ?? a.cells[colIdx].textContent;
      const bv = b.cells[colIdx].dataset.sort ?? b.cells[colIdx].textContent;
      const an = parseFloat(av), bn = parseFloat(bv);
      const both = !isNaN(an) && !isNaN(bn);
      const cmp = both ? an - bn : String(av).localeCompare(String(bv));
      return asc ? cmp : -cmp;
    }});
    rows.forEach(r => tbody.appendChild(r));
  }}

  ths.forEach((th, i) => {{
    th.addEventListener("click", () => {{
      const asc = !th.classList.contains("sort-asc");
      ths.forEach(x => x.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(asc ? "sort-asc" : "sort-desc");
      sortBy(i, asc);
    }});
  }});

  // Initial sort: total downloads descending
  ths[2].classList.add("sort-desc");
  sortBy(2, false);
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
    print(f"  Table rows: {len(table_rows)}")


if __name__ == "__main__":
    main()
