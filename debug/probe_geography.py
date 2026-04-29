#!/usr/bin/env python3
"""
Phase 2c probe: find an endpoint that returns geographic breakdown of
downloads (country / region / state) for curated ICPSR studies.

Strategy:
  1. Try plausible API paths under /pcms/metrics/data/api/
  2. If none hit, fetch the public PCMS utilization page and grep its
     inline scripts for any URL containing 'country', 'region', etc.
  3. Also pull the dashboard JS bundle and look for endpoint patterns.

Usage:
    python debug/probe_geography.py
    python debug/probe_geography.py 38528
"""

import json
import re
import sys

import cloudscraper

SID = int(sys.argv[1]) if len(sys.argv) > 1 else 38528  # high-traffic curated study
START_DATE = "01/01/2020"
END_DATE = "04/29/2026"

PCMS_BASE = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api"
DASHBOARD_PAGE = f"https://pcms.icpsr.umich.edu/pcms/metrics/studies/{SID}/utilization"

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

referer = DASHBOARD_PAGE


def try_paths() -> None:
    print(f"\n=== 1. Try plausible API paths (study {SID}) ===")
    paths = [
        "country", "countries",
        "region", "regions",
        "state", "states",
        "geography", "geo",
        "location", "locations",
        "countryCount", "regionCount", "stateCount",
        "downloadCountry", "downloadRegion", "downloadState",
        "geographic", "geographics",
        "map", "mapData",
    ]
    for path in paths:
        url = f"{PCMS_BASE}/{path}"
        try:
            r = scraper.get(url, params={"studyId": SID, "startDt": START_DATE, "endDt": END_DATE},
                            headers={"Referer": referer}, timeout=20)
            ct = r.headers.get("Content-Type", "")
            preview = r.text[:120].replace("\n", " ").strip()
            label = f"{r.status_code:>3}  {ct[:32]:<32}"
            print(f"  {label}  {url}")
            if r.status_code == 200 and ("json" in ct.lower() or r.text.lstrip().startswith(("{", "["))):
                try:
                    j = r.json()
                    if isinstance(j, list):
                        print(f"       -> JSON list of {len(j)} items")
                        if j:
                            print(f"          first item keys: {list(j[0].keys()) if isinstance(j[0], dict) else type(j[0]).__name__}")
                            print(f"          first 3 items:")
                            for item in j[:3]:
                                print(f"            {json.dumps(item)}")
                    elif isinstance(j, dict):
                        print(f"       -> JSON dict, keys: {list(j.keys())[:10]}")
                        print(f"          {json.dumps(j)[:300]}")
                except Exception:
                    pass
        except Exception as e:
            print(f"  ERR  {url}: {e}")


def grep_dashboard_html() -> None:
    print(f"\n=== 2. Grep dashboard utilization page for geo URLs ===")
    print(f"URL: {DASHBOARD_PAGE}")
    try:
        r = scraper.get(DASHBOARD_PAGE, timeout=30)
        print(f"  HTTP {r.status_code}, len: {len(r.text):,}")
        if r.status_code != 200:
            print(f"  body preview: {r.text[:300]}")
            return
        html = r.text

        # Find URL-shaped strings containing geo keywords
        keywords = ("country", "region", "state", "geo", "location", "map", "world")
        candidates = set()
        for m in re.finditer(r'["\']((?:https?:)?[/\w][^"\'\s<>]{4,250})["\']', html):
            url = m.group(1)
            if any(k in url.lower() for k in keywords):
                if any(url.lower().endswith(ext) for ext in
                       (".css", ".png", ".jpg", ".svg", ".gif", ".woff", ".woff2", ".ttf")):
                    continue
                candidates.add(url)
        print(f"  found {len(candidates)} candidate URLs:")
        for c in sorted(candidates):
            print(f"    {c}")

        # Also pull script tags that look like config / variable assignments
        print(f"\n  Inline scripts mentioning country/region/geo:")
        for m in re.finditer(r"<script[^>]*>([\s\S]*?)</script>", html):
            body = m.group(1)
            if any(k in body.lower() for k in ("country", "region", "geographic")):
                # Find variable-like assignments
                for assign in re.finditer(r'(?:var\s+\w+|window\.\w+|[\w]+)\s*=\s*[\'"]?([^\'";\n]{0,300})', body):
                    val = assign.group(1).strip()
                    if any(k in val.lower() for k in ("country", "region", "geo")):
                        print(f"    {val[:200]}")
                # Also find URL endpoints
                for url_m in re.finditer(r"['\"]((?:https?:)?/[^'\"\s<>]{4,250})['\"]", body):
                    url = url_m.group(1)
                    if any(k in url.lower() for k in ("country", "region", "geo")):
                        print(f"    URL: {url}")
                break  # one such script is enough
    except Exception as e:
        print(f"  ERROR: {e}")


def fetch_studies_js() -> None:
    """The dashboard uses a JS bundle similar to ProjectUsage.js for openICPSR.
    Try to fetch the equivalent and grep for geographic endpoints."""
    print(f"\n=== 3. Fetch likely dashboard JS bundles, grep for geo endpoints ===")
    candidates = [
        "https://pcms.icpsr.umich.edu/pcms/resources/js/app/studyMetrics/StudyMetrics.js",
        "https://pcms.icpsr.umich.edu/pcms/resources/js/app/utilization/Utilization.js",
        "https://pcms.icpsr.umich.edu/pcms/resources/js/app/utilization/utilization.js",
        "https://pcms.icpsr.umich.edu/pcms/resources/js/app/dashboard/Dashboard.js",
    ]
    for url in candidates:
        try:
            r = scraper.get(url, timeout=20)
            print(f"  {r.status_code}  len={len(r.text):>6,}  {url}")
        except Exception as e:
            print(f"  ERR  {url}: {e}")


try_paths()
grep_dashboard_html()
fetch_studies_js()
