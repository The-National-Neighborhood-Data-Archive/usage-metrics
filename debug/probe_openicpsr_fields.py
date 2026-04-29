#!/usr/bin/env python3
"""
Phase 1a probe: confirm exact field names returned by the openICPSR
usage/view endpoint, so we know what keys to read for total_views and
publications (in addition to totalDownloads).

Usage:
    python debug/probe_openicpsr_fields.py
    python debug/probe_openicpsr_fields.py 237305
"""

import json
import sys

import cloudscraper

DEFAULT_IDS = [110641, 237305, 302937]  # mix of openICPSR 6-digit IDs from STUDY_IDS
IDS = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_IDS

URL = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api/openicpsr/projects/{sid}/usage/view"

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

for sid in IDS:
    print(f"\n=== {sid} ===")
    try:
        r = scraper.get(URL.format(sid=sid), params={"level": "project"}, timeout=30)
        print(f"HTTP {r.status_code}  Content-Type: {r.headers.get('Content-Type', '')}")
        try:
            j = r.json()
            print(f"Top-level keys: {list(j.keys()) if isinstance(j, dict) else type(j).__name__}")
            print("Full response:")
            print(json.dumps(j, indent=2)[:2000])
        except Exception as e:
            print(f"Not JSON: {e}")
            print(r.text[:500])
    except Exception as e:
        print(f"ERROR: {e}")
