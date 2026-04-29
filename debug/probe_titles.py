#!/usr/bin/env python3
"""
Phase 1b probe: confirm DOI URLs redirect to a usable page that contains a
JSON-LD <script type="application/ld+json"> block with a `name` field.

Tests one curated (5-digit) and two openICPSR (6-digit) studies.

Usage:
    python debug/probe_titles.py
    python debug/probe_titles.py 38567
"""

import json
import re
import sys

import cloudscraper

DEFAULT_IDS = [38567, 110641, 237305]
IDS = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_IDS

JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def doi_url(study_id: int) -> str:
    if study_id < 100000:
        return f"https://doi.org/10.3886/ICPSR{study_id}"
    return f"https://doi.org/10.3886/E{study_id}"


scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

for sid in IDS:
    print(f"\n=== {sid} ===")
    url = doi_url(sid)
    print(f"DOI URL: {url}")
    try:
        r = scraper.get(url, timeout=30, allow_redirects=True)
        print(f"HTTP {r.status_code}, len: {len(r.text):,}, final: {r.url}")
        if r.history:
            print(f"Redirects: {len(r.history)} hop(s)")

        blocks = JSONLD_RE.findall(r.text)
        print(f"Found {len(blocks)} JSON-LD block(s)")
        for i, b in enumerate(blocks):
            try:
                j = json.loads(b)
                if isinstance(j, list):
                    print(f"  block {i+1}: list of {len(j)} items")
                    for k, item in enumerate(j):
                        if isinstance(item, dict) and "name" in item:
                            print(f"    [{k}] @type={item.get('@type')!r:<20} name={item['name']!r}")
                elif isinstance(j, dict):
                    print(f"  block {i+1}: dict, @type={j.get('@type')!r}, keys={list(j.keys())[:8]}")
                    if "name" in j:
                        print(f"    name = {j['name']!r}")
            except json.JSONDecodeError as e:
                print(f"  block {i+1}: JSON parse error: {e}")
                print(f"    preview: {b[:200]!r}")
    except Exception as e:
        print(f"ERROR: {e}")
