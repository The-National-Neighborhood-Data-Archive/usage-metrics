#!/usr/bin/env python3
"""
NaNDA Usage Metrics Scraper

Pulls download / user / institution counts for every NaNDA study and writes
them to data/nanda_usage_stats_YYYY-MM-DD.csv.

Inventory-driven: `inventory.csv` (sibling file) is the source of truth for
two things:
  - Dataset title (joined onto each row by study_id)
  - Routing (the `archive` column — "ICPSR" or "openICPSR" — picks which
    API set to call; ID-length heuristics are no longer used)

API sources:

  1. PCMS metrics API (pcms.icpsr.umich.edu) — for archive=ICPSR (curated):
     - Rich breakdown: data vs documentation downloads, unique users,
       institutions.

  2. PCMS openICPSR project-usage API — for archive=openICPSR:
       /pcms/metrics/data/api/openicpsr/projects/{id}/usage/view?level=project
     - Returns total_downloads and total_views. All-time, no date params.

  3. ICPSR search API (search.icpsr.umich.edu) — curated only:
     - Returns the count of related publications.

Uses cloudscraper because pcms.icpsr.umich.edu sits behind Cloudflare.
"""

import time
from datetime import datetime
from pathlib import Path

import cloudscraper
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("data")
INVENTORY_PATH = Path(__file__).parent / "inventory.csv"

# Date range: NaNDA's first ICPSR release was in 2020.
START_DATE = "01/01/2020"
END_DATE = datetime.now().strftime("%m/%d/%Y")

# Polite pause between studies.
REQUEST_DELAY = 1

# Full NaNDA study list (curated ICPSR + openICPSR).
# When a new study is published, append its ID here.
STUDY_IDS = [
    38567, 38649, 38974, 39093, 39378, 38559, 38598, 38579,
    38586, 38597, 38585, 38605, 38569, 38528, 38580, 38584,
    38606, 38506, 38858, 110641, 110663, 111107, 111109, 115006,
    115323, 115404, 115407, 115408, 115543, 115967, 115972, 115973,
    115981, 117163, 117866, 117921, 119451, 119803, 120088, 120462,
    120463, 120907, 121741, 123001, 123042, 123541, 123542, 123801,
    123802, 124721, 124801, 125223, 125781, 126082, 127042, 127262,
    127681, 127682, 128281, 128282, 128841, 128862, 130282, 130542,
    134561, 141121, 155022, 155025, 156024, 156041, 156042, 156043,
    156045, 159902, 159941, 159961, 159981, 160261, 160262, 190141,
    200038, 207966, 208207, 208366, 208682, 208684, 208751, 208906,
    208907, 209050, 209163, 209164, 209313, 209324, 210581, 220701,
    222263, 222901, 230941, 237305, 301419, 302343, 302937, 302178,
]
# Dedupe while preserving order.
STUDY_IDS = list(dict.fromkeys(STUDY_IDS))

# PCMS API endpoints (curated ICPSR — rich breakdown)
PCMS_DOWNLOAD_COUNT = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadCount"
PCMS_DOWNLOAD_INFO  = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadInfo"
PCMS_INSTITUTION    = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/institution"

# openICPSR usage view (the React component on the openICPSR project page hits this)
OPENICPSR_USAGE_URL = (
    "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/openicpsr/projects/{sid}/usage/view"
)

# Publications search API — curated ICPSR only.
# Returns Solr-style JSON with `response.numFound` = count of related publications.
PUBLICATIONS_API = (
    "https://search.icpsr.umich.edu/search/api/1.0/default/search/"
    "applications/icpsr/modules/icpsr/publications"
)

CSV_COLUMNS = [
    "study_id",
    "dataset_title",
    "total_downloads",
    "total_views",
    "publications",
    "data_downloads",
    "documentation_downloads",
    "unique_users",
    "num_institutions",
    "status",
    "error_message",
    "timestamp",
]

TIMESERIES_COLUMNS = [
    "study_id",
    "year",
    "month",
    "data_downloads",
    "documentation_downloads",
    "total_downloads",
    "timestamp",
]


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def load_inventory(path: Path = INVENTORY_PATH) -> dict:
    """
    Load inventory.csv into a dict keyed by study_id. Each value is a dict
    with at least: archive, deposit_via, status, title, doi, url, version,
    version_date. Used for title lookup and archive-based routing.
    """
    inv = pd.read_csv(path, encoding="utf-8")
    out: dict = {}
    for _, row in inv.iterrows():
        sid = int(row["study_id"])
        out[sid] = {
            "archive":      row.get("archive"),
            "deposit_via":  row.get("deposit_via"),
            "status":       row.get("status"),
            "title":        row.get("title"),
            "version":      row.get("version"),
            "version_date": row.get("version_date"),
            "doi":          row.get("doi"),
            "url":          row.get("url"),
        }
    return out


def make_scraper() -> cloudscraper.CloudScraper:
    """Cloudscraper session that mimics a real browser well enough for ICPSR."""
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return scraper


def fetch_pcms(study_id: int, scraper) -> dict:
    """
    Try the PCMS endpoints. Returns a dict with keys:
        data_downloads, documentation_downloads, total_downloads,
        unique_users, num_institutions, has_data (bool)
    `has_data` is True only if downloadCount returned non-empty results
    (i.e., this is a curated ICPSR study covered by PCMS).
    """
    out = {
        "data_downloads": 0,
        "documentation_downloads": 0,
        "total_downloads": 0,
        "unique_users": None,
        "num_institutions": 0,
        "has_data": False,
    }

    params = {"studyId": study_id, "startDt": START_DATE, "endDt": END_DATE}
    referer = f"https://pcms.icpsr.umich.edu/pcms/metrics/studies/{study_id}/utilization"
    headers = {"Referer": referer}

    # Download counts
    r = scraper.get(PCMS_DOWNLOAD_COUNT, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    download_data = r.json() or []
    if not download_data:
        return out  # openICPSR — PCMS doesn't cover it

    out["has_data"] = True
    data_total = sum(item["downloads"] for item in download_data if item.get("type") == "data")
    doc_total  = sum(item["downloads"] for item in download_data if item.get("type") == "documentation")
    out["data_downloads"] = data_total
    out["documentation_downloads"] = doc_total
    out["total_downloads"] = data_total + doc_total

    # Unique users
    r = scraper.get(PCMS_DOWNLOAD_INFO, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    info_data = r.json() or []
    if info_data:
        out["unique_users"] = info_data[0].get("uniqueUsers")

    # Institutions
    r = scraper.get(PCMS_INSTITUTION, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    inst_data = r.json() or []
    out["num_institutions"] = len(inst_data)

    return out


def fetch_openicpsr_usage(study_id: int, scraper) -> dict:
    """
    For openICPSR projects, hit the project-usage view endpoint that the
    React component on the page itself calls. Returns a dict with keys
    total_downloads, total_views (both int, 0 if missing).
    """
    url = OPENICPSR_USAGE_URL.format(sid=study_id)
    r = scraper.get(url, params={"level": "project"}, timeout=30)
    r.raise_for_status()
    j = r.json() or {}
    return {
        "total_downloads": int(j.get("totalDownloads") or 0),
        "total_views":     int(j.get("totalViews") or 0),
    }


def fetch_publications_count(study_id: int, scraper) -> int:
    """
    Count of related publications for curated ICPSR via the search API.
    Reads `response.numFound` from a Solr-style JSON response.
    """
    params = {
        "requestUrl": f"https://www.icpsr.umich.edu/web/ICPSR/studies/{study_id}/publications",
        "isUserLoggedIn": "false",
        "STUDYQ": study_id,
    }
    r = scraper.get(PUBLICATIONS_API, params=params, timeout=30)
    r.raise_for_status()
    return int(r.json().get("response", {}).get("numFound", 0))


def scrape_study(study_id: int, scraper, inventory: dict) -> dict:
    """Pull one study's metrics. Returns a dict matching CSV_COLUMNS.

    Routing comes from inventory['archive']:
      - 'ICPSR'     → PCMS endpoints + publications search API
      - 'openICPSR' → openICPSR project-usage endpoint
      - anything else (or missing) → log and skip metric fetches
    """
    row = {
        "study_id": study_id,
        "dataset_title": None,
        "total_downloads": 0,
        "total_views": None,
        "publications": None,
        "data_downloads": 0,
        "documentation_downloads": 0,
        "unique_users": None,
        "num_institutions": 0,
        "status": "success",
        "error_message": "",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        inv_entry = inventory.get(study_id, {})
        row["dataset_title"] = inv_entry.get("title")
        archive = inv_entry.get("archive")

        if archive == "openICPSR":
            # Includes RDE-deposited datasets — data lives in openICPSR
            # regardless of deposit pathway.
            try:
                usage = fetch_openicpsr_usage(study_id, scraper)
                row["total_downloads"] = usage["total_downloads"]
                row["total_views"]     = usage["total_views"]
            except Exception as e:
                row["error_message"] = f"openicpsr-usage fallback: {str(e)[:160]}"
        elif archive == "ICPSR":
            # Curated — PCMS endpoints + publications search API.
            pcms = fetch_pcms(study_id, scraper)
            if pcms["has_data"]:
                row["data_downloads"] = pcms["data_downloads"]
                row["documentation_downloads"] = pcms["documentation_downloads"]
                row["total_downloads"] = pcms["total_downloads"]
                row["unique_users"] = pcms["unique_users"]
                row["num_institutions"] = pcms["num_institutions"]
                try:
                    row["publications"] = fetch_publications_count(study_id, scraper)
                except Exception as e:
                    msg = f"pubs: {str(e)[:80]}"
                    row["error_message"] = (row["error_message"] + "; " + msg).strip("; ")
        else:
            row["error_message"] = f"unknown archive value: {archive!r}"
        return row

    except Exception as e:
        row["status"] = "error"
        row["error_message"] = str(e)[:200]
        return row


def scrape_all(study_ids, scraper, inventory: dict, delay=REQUEST_DELAY) -> pd.DataFrame:
    rows = []
    n = len(study_ids)
    for i, sid in enumerate(study_ids, 1):
        row = scrape_study(sid, scraper, inventory)
        rows.append(row)
        if row["status"] == "success":
            tag = "ok " if row["total_downloads"] else "0  "
            print(
                f"  [{i:>3}/{n}] {sid:<7} {tag} "
                f"{row['total_downloads']} dl, "
                f"{row['unique_users']} users, "
                f"{row['num_institutions']} insts"
            )
        else:
            print(f"  [{i:>3}/{n}] {sid:<7} ERR  {row['error_message'][:80]}")
        if i < n:
            time.sleep(delay)
    return pd.DataFrame(rows, columns=CSV_COLUMNS)


def fetch_timeseries(study_id: int, scraper) -> list:
    """
    Pull the monthly download time-series for a curated ICPSR study.
    PCMS /downloadCount returns one item per (year, month, type) bucket.
    Returns the raw items list (each dict has month, year, downloads, type).
    """
    params = {"studyId": study_id, "startDt": START_DATE, "endDt": END_DATE}
    referer = f"https://pcms.icpsr.umich.edu/pcms/metrics/studies/{study_id}/utilization"
    r = scraper.get(PCMS_DOWNLOAD_COUNT, params=params,
                    headers={"Referer": referer}, timeout=30)
    r.raise_for_status()
    return r.json() or []


def scrape_timeseries(study_ids, scraper, inventory: dict, delay=REQUEST_DELAY) -> pd.DataFrame:
    """
    Build a long-format monthly time-series for all curated ICPSR studies
    in `study_ids`. Curated = inventory['archive'] == 'ICPSR'. openICPSR
    studies are skipped — no time-series endpoint exists for them.

    One row per (study_id, year, month) with separate columns for data
    and documentation downloads. Months with zero activity are omitted.
    """
    curated = [sid for sid in study_ids
               if inventory.get(sid, {}).get("archive") == "ICPSR"]
    n = len(curated)
    print(f"\nFetching monthly time-series for {n} curated studies")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    long_rows = []
    for i, sid in enumerate(curated, 1):
        try:
            items = fetch_timeseries(sid, scraper)
            for item in items:
                long_rows.append({
                    "study_id": sid,
                    "year":  int(item["year"]),
                    "month": int(item["month"]),
                    "type":  item.get("type"),
                    "downloads": int(item.get("downloads") or 0),
                })
            print(f"  [{i:>3}/{n}] {sid:<7} ok   {len(items)} buckets")
        except Exception as e:
            print(f"  [{i:>3}/{n}] {sid:<7} ERR  {str(e)[:80]}")
        if i < n:
            time.sleep(delay)

    if not long_rows:
        return pd.DataFrame(columns=TIMESERIES_COLUMNS)

    long_df = pd.DataFrame(long_rows)
    wide = (long_df
            .pivot_table(index=["study_id", "year", "month"],
                         columns="type", values="downloads",
                         aggfunc="sum", fill_value=0)
            .reset_index())
    wide.columns.name = None
    # Ensure both type columns exist even if one type never appeared.
    for col in ("data", "documentation"):
        if col not in wide.columns:
            wide[col] = 0
    wide = wide.rename(columns={
        "data": "data_downloads",
        "documentation": "documentation_downloads",
    })
    wide["total_downloads"] = wide["data_downloads"] + wide["documentation_downloads"]
    wide["timestamp"] = timestamp
    wide = wide.sort_values(["study_id", "year", "month"]).reset_index(drop=True)
    return wide[TIMESERIES_COLUMNS]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    inventory = load_inventory()
    print(f"Loaded inventory: {len(inventory)} studies")
    print(f"Scraping {len(STUDY_IDS)} NaNDA studies ({START_DATE} -> {END_DATE})")
    scraper = make_scraper()
    df = scrape_all(STUDY_IDS, scraper, inventory)

    dated_path  = OUTPUT_DIR / f"nanda_usage_stats_{today}.csv"
    latest_path = OUTPUT_DIR / "nanda_usage_stats_latest.csv"
    df.to_csv(dated_path, index=False)
    df.to_csv(latest_path, index=False)

    n_ok    = (df["status"] == "success").sum()
    n_err   = (df["status"] == "error").sum()
    n_real  = ((df["status"] == "success") & (df["total_downloads"] > 0)).sum()

    print()
    print(f"Wrote {dated_path}")
    print(f"Wrote {latest_path}")
    print(f"  {n_ok} success / {n_err} errors / {n_real} with non-zero downloads")

    # Monthly time-series (curated ICPSR only)
    ts_df = scrape_timeseries(STUDY_IDS, scraper, inventory)
    ts_dated  = OUTPUT_DIR / f"nanda_usage_timeseries_{today}.csv"
    ts_latest = OUTPUT_DIR / "nanda_usage_timeseries_latest.csv"
    ts_df.to_csv(ts_dated, index=False)
    ts_df.to_csv(ts_latest, index=False)

    print()
    print(f"Wrote {ts_dated}")
    print(f"Wrote {ts_latest}")
    print(f"  {len(ts_df):,} monthly rows across "
          f"{ts_df['study_id'].nunique() if len(ts_df) else 0} curated studies")


if __name__ == "__main__":
    main()
