#!/usr/bin/env python3
"""
Phase 1c probe: confirm fields returned by the PCMS /institution endpoint
so we know how to extract top-N institutions and what the sort order is.

Usage:
    python debug/probe_institutions.py
    python debug/probe_institutions.py 38567 38528
"""

import json
import sys

import cloudscraper

DEFAULT_IDS = [38567, 38528, 39093]
IDS = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_IDS

URL = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/institution"
START_DATE = "01/01/2020"
END_DATE = "04/29/2026"

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

for sid in IDS:
    print(f"\n=== {sid} ===")
    referer = f"https://pcms.icpsr.umich.edu/pcms/metrics/studies/{sid}/utilization"
    try:
        r = scraper.get(URL, params={"studyId": sid, "startDt": START_DATE, "endDt": END_DATE},
                        headers={"Referer": referer}, timeout=30)
        print(f"HTTP {r.status_code}  Content-Type: {r.headers.get('Content-Type', '')}")
        j = r.json()
        if not isinstance(j, list):
            print(f"Unexpected shape: {type(j).__name__}")
            print(json.dumps(j, indent=2)[:500])
            continue
        print(f"List length: {len(j)}")
        if j:
            print(f"First item keys: {list(j[0].keys()) if isinstance(j[0], dict) else type(j[0]).__name__}")
            print("First 5 items (raw API order):")
            for item in j[:5]:
                print(f"  {json.dumps(item)}")
            print("Last 3 items:")
            for item in j[-3:]:
                print(f"  {json.dumps(item)}")
    except Exception as e:
        print(f"ERROR: {e}")
