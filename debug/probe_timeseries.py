#!/usr/bin/env python3
"""
Phase 2b probe: determine whether PCMS /downloadCount returns monthly
buckets natively or only cumulative totals.

We test three date ranges on a single study and compare item counts:
  1. Full range (01/01/2020 -> today)
  2. Single month (01/01/2020 -> 01/31/2020)
  3. Three months (01/01/2020 -> 03/31/2020)

If the item count scales with the number of months, buckets are native.
If it stays at 2 (data + documentation), we need to loop month-by-month.

Also probes /downloadInfo to see if uniqueUsers is bucketed.

Usage:
    python debug/probe_timeseries.py
    python debug/probe_timeseries.py 38528
"""

import json
import sys

import cloudscraper

DEFAULT_ID = 38528  # most-downloaded curated study, plenty of history to bucket
SID = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ID

PCMS_DOWNLOAD_COUNT = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadCount"
PCMS_DOWNLOAD_INFO  = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadInfo"

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

referer = f"https://pcms.icpsr.umich.edu/pcms/metrics/studies/{SID}/utilization"
headers = {"Referer": referer}

RANGES = [
    ("Full range (lifetime)",  "01/01/2020", "04/29/2026"),
    ("Single month (Jan 2020)", "01/01/2020", "01/31/2020"),
    ("Three months (Q1 2020)",  "01/01/2020", "03/31/2020"),
    ("Single month (Jan 2024)", "01/01/2024", "01/31/2024"),
]


def probe(endpoint_url: str, label: str) -> None:
    print(f"\n========== {label} — study {SID} ==========")
    print(f"Endpoint: {endpoint_url}")
    for name, start, end in RANGES:
        print(f"\n--- {name}: {start} -> {end} ---")
        try:
            r = scraper.get(endpoint_url,
                            params={"studyId": SID, "startDt": start, "endDt": end},
                            headers=headers, timeout=30)
            j = r.json()
            if not isinstance(j, list):
                print(f"  Unexpected shape: {type(j).__name__}")
                print(f"  {json.dumps(j, indent=2)[:400]}")
                continue
            print(f"  HTTP {r.status_code}, list length: {len(j)}")
            if j:
                print(f"  First item keys: {list(j[0].keys())}")
                print(f"  All items:")
                for item in j[:20]:
                    print(f"    {json.dumps(item)}")
                if len(j) > 20:
                    print(f"    ... ({len(j) - 20} more)")
        except Exception as e:
            print(f"  ERROR: {e}")


probe(PCMS_DOWNLOAD_COUNT, "/downloadCount")
probe(PCMS_DOWNLOAD_INFO,  "/downloadInfo")
