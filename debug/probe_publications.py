#!/usr/bin/env python3
"""
Phase 2a probe: find a stable source for the publications count for
curated ICPSR studies. Tries three approaches in order:

  1. PCMS API variants — /publications, /publication, /citation, /citations
  2. JSON-LD `citation` array on the DOI study page
  3. HTML scrape of the study /publications page (visible total count)

Compare results across all three for one or more studies. Pick the
approach that gives a non-zero, plausible count consistently.

Usage:
    python debug/probe_publications.py
    python debug/probe_publications.py 38567 38528
"""

import json
import re
import sys

import cloudscraper

DEFAULT_IDS = [38567, 38528, 39093]
IDS = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_IDS

START_DATE = "01/01/2020"
END_DATE = "04/29/2026"

PCMS_BASE = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api"
DOI_CURATED_URL = "https://doi.org/10.3886/ICPSR{sid}"
PUBS_PAGE = "https://www.icpsr.umich.edu/web/ICPSR/studies/{sid}/publications"

JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
})


def try_pcms_api(sid: int) -> None:
    print(f"\n  --- 1. PCMS API variants ---")
    referer = f"https://pcms.icpsr.umich.edu/pcms/metrics/studies/{sid}/utilization"
    paths = [
        "publications", "publication", "citation", "citations",
        "publicationsCount", "relatedPublication", "publicationCount",
    ]
    for path in paths:
        url = f"{PCMS_BASE}/{path}"
        try:
            r = scraper.get(url, params={"studyId": sid, "startDt": START_DATE, "endDt": END_DATE},
                            headers={"Referer": referer}, timeout=20)
            ct = r.headers.get("Content-Type", "")
            preview = r.text[:120].replace("\n", " ").strip()
            print(f"    {r.status_code:>3}  {ct[:30]:<30}  {url}  -> {preview!r}")
            if r.status_code == 200 and ("json" in ct.lower() or r.text.lstrip().startswith(("{", "["))):
                try:
                    j = r.json()
                    if isinstance(j, list):
                        print(f"         JSON list of {len(j)} items")
                        if j:
                            print(f"         first item keys: {list(j[0].keys()) if isinstance(j[0], dict) else type(j[0]).__name__}")
                            print(f"         first item: {json.dumps(j[0])[:200]}")
                    elif isinstance(j, dict):
                        print(f"         JSON dict, keys: {list(j.keys())[:8]}")
                        print(f"         {json.dumps(j)[:200]}")
                except Exception:
                    pass
        except Exception as e:
            print(f"    ERR  {url}: {e}")


def try_jsonld(sid: int) -> None:
    print(f"\n  --- 2. JSON-LD `citation` field on DOI page ---")
    url = DOI_CURATED_URL.format(sid=sid)
    try:
        r = scraper.get(url, timeout=30, allow_redirects=True)
        print(f"    HTTP {r.status_code}, final: {r.url}")
        m = JSONLD_RE.search(r.text)
        if not m:
            print("    no JSON-LD block found")
            return
        j = json.loads(m.group(1))
        if isinstance(j, list):
            j = next((x for x in j if isinstance(x, dict)), {})
        keys = list(j.keys()) if isinstance(j, dict) else []
        print(f"    JSON-LD keys: {keys}")
        for key in ("citation", "isReferencedBy", "publication", "publications"):
            if key in j:
                val = j[key]
                if isinstance(val, list):
                    print(f"    `{key}` is a list of {len(val)} items")
                    if val:
                        print(f"      first item: {json.dumps(val[0])[:300]}")
                else:
                    print(f"    `{key}`: {json.dumps(val)[:300]}")
    except Exception as e:
        print(f"    ERROR: {e}")


def try_publications_page(sid: int) -> None:
    print(f"\n  --- 3. HTML scrape of /publications page ---")
    url = PUBS_PAGE.format(sid=sid)
    try:
        r = scraper.get(url, timeout=30, allow_redirects=True)
        print(f"    HTTP {r.status_code}, len: {len(r.text):,}, final: {r.url}")
        # Look for "X publications" or "X results" or similar count phrasing
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text)
        for kw in ("publications found", "publications", "results", "citations"):
            for m in re.finditer(rf"([\d,]+)\s+{kw}\b", text, re.I):
                snippet = text[max(0, m.start()-40):m.end()+40]
                print(f"    match: ...{snippet}...")
                break
    except Exception as e:
        print(f"    ERROR: {e}")


for sid in IDS:
    print(f"\n=== {sid} ===")
    try_pcms_api(sid)
    try_jsonld(sid)
    try_publications_page(sid)
