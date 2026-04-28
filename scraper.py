#!/usr/bin/env python3
"""
NaNDA Usage Metrics Scraper

Pulls download / user / institution counts for every NaNDA study and writes
them to data/nanda_usage_stats_YYYY-MM-DD.csv.

Two API sources, used together so we get coverage for both curated ICPSR
(5-digit) AND openICPSR (6-digit) studies:

  1. PCMS metrics API (pcms.icpsr.umich.edu):
     - Rich breakdown: data vs documentation downloads, unique users,
       institutions.
     - Covers CURATED ICPSR only. openICPSR studies come back empty.

  2. PCMS openICPSR project-usage API:
       /pcms/metrics/data/api/openicpsr/projects/{id}/usage/view?level=project
     - Returns total_downloads (and total_views, publications) for openICPSR
       projects. All-time, no date params.

Logic per study: try PCMS first; if it returns data, use it. Otherwise fall
back to the usage-statistics API for at least a total_downloads number.

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
    207966, 208207, 208366, 208682, 208684, 208751, 208906, 208907,
    209050, 209163, 209164, 209313, 209324, 210581, 220701, 222263,
    222901, 230941, 237305, 301419, 302343, 302937, 302178,
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

CSV_COLUMNS = [
    "study_id",
    "total_downloads",
    "data_downloads",
    "documentation_downloads",
    "unique_users",
    "num_institutions",
    "status",
    "error_message",
    "timestamp",
]


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

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


def fetch_openicpsr_usage(study_id: int, scraper) -> int:
    """
    For openICPSR projects, hit the project-usage view endpoint that the
    React component on the page itself calls. Returns total_downloads as int
    (0 if missing).
    """
    url = OPENICPSR_USAGE_URL.format(sid=study_id)
    r = scraper.get(url, params={"level": "project"}, timeout=30)
    r.raise_for_status()
    j = r.json() or {}
    total = j.get("totalDownloads", 0)
    return int(total) if total is not None else 0


def scrape_study(study_id: int, scraper) -> dict:
    """Pull one study's metrics. Returns a dict matching CSV_COLUMNS."""
    row = {
        "study_id": study_id,
        "total_downloads": 0,
        "data_downloads": 0,
        "documentation_downloads": 0,
        "unique_users": None,
        "num_institutions": 0,
        "status": "success",
        "error_message": "",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        pcms = fetch_pcms(study_id, scraper)
        if pcms["has_data"]:
            # Curated ICPSR — use PCMS numbers.
            row["data_downloads"] = pcms["data_downloads"]
            row["documentation_downloads"] = pcms["documentation_downloads"]
            row["total_downloads"] = pcms["total_downloads"]
            row["unique_users"] = pcms["unique_users"]
            row["num_institutions"] = pcms["num_institutions"]
        else:
            # openICPSR — hit the openICPSR project-usage endpoint instead.
            try:
                row["total_downloads"] = fetch_openicpsr_usage(study_id, scraper)
            except Exception as e:
                # Don't fail the whole row if just the fallback breaks —
                # record the issue but keep the (zero) PCMS values.
                row["error_message"] = f"openicpsr-usage fallback: {str(e)[:160]}"
        return row

    except Exception as e:
        row["status"] = "error"
        row["error_message"] = str(e)[:200]
        return row


def scrape_all(study_ids, scraper, delay=REQUEST_DELAY) -> pd.DataFrame:
    rows = []
    n = len(study_ids)
    for i, sid in enumerate(study_ids, 1):
        row = scrape_study(sid, scraper)
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"Scraping {len(STUDY_IDS)} NaNDA studies ({START_DATE} -> {END_DATE})")
    scraper = make_scraper()
    df = scrape_all(STUDY_IDS, scraper)

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


if __name__ == "__main__":
    main()
