#!/usr/bin/env python3
"""
Probe openICPSR for a download/stats endpoint we can use for self-published
NaNDA studies (the 6-digit IDs the pcms API doesn't cover).

Strategy:
  1. Fetch the project page HTML
  2. Grep for URL patterns that look stats/metrics-related
  3. Try a handful of plausible direct API paths

Run:
    python openicpsr_probe.py            # default project 237305 (Air Conditioning)
    python openicpsr_probe.py 200038     # any openICPSR project id

Paste the full output back to Claude.
"""

import json
import re
import sys

try:
    import cloudscraper
except ImportError:
    sys.exit("Missing dependency. Install with: pip install cloudscraper")


PROJECT_ID = sys.argv[1] if len(sys.argv) > 1 else "237305"
PROJECT_URL = f"https://www.openicpsr.org/openicpsr/project/{PROJECT_ID}/version/V1/view"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": PROJECT_URL,
}

SCRAPER = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)


def fetch_page():
    print(f"=== Fetching project page ===")
    print(f"URL: {PROJECT_URL}")
    r = SCRAPER.get(PROJECT_URL, headers=HEADERS, timeout=30)
    print(f"HTTP {r.status_code}, len: {len(r.text):,}")
    return r.text


def grep_patterns(html: str) -> None:
    print("\n=== URL patterns matching stats/metrics/download keywords ===")
    keywords = ("stats", "metric", "download", "usage", "count", "view", "analytic")
    # Find quoted URLs/paths
    candidates = set()
    for m in re.finditer(r'["\']((?:https?:)?/[^"\'\s<>]{4,200})["\']', html):
        url = m.group(1)
        if any(k in url.lower() for k in keywords):
            # Filter out asset URLs
            if any(url.lower().endswith(ext) for ext in
                   (".css", ".js", ".png", ".jpg", ".svg", ".gif", ".woff", ".woff2", ".ttf")):
                continue
            candidates.add(url)
    for c in sorted(candidates):
        print(f"  {c}")
    if not candidates:
        print("  (none found)")


def grep_inline_scripts(html: str) -> None:
    print("\n=== Inline scripts mentioning stats/AJAX endpoints ===")
    # Pull script tag bodies
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    interesting = []
    for s in scripts:
        if any(k in s.lower() for k in ("stats", "downloadcount", "metrics", "$.ajax", "fetch(", "axios.")):
            interesting.append(s)
    print(f"  found {len(interesting)} candidate scripts")
    for i, s in enumerate(interesting[:3]):
        print(f"\n  --- script {i+1} (len={len(s)}) ---")
        # Print the first ~800 chars
        print("    " + s.strip()[:800].replace("\n", "\n    "))


def grep_visible_numbers(html: str) -> None:
    print("\n=== Visible 'Downloads/Views' counts on the page ===")
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    for kw in ("Downloads", "Views", "Citations", "Files Downloaded"):
        for m in re.finditer(rf"([\d,]+)[^\d]{{0,20}}{kw}|{kw}[^\d]{{0,20}}([\d,]+)", text, re.I):
            print(f"  ...{text[max(0,m.start()-40):m.end()+40]}...")
            break


def try_direct_endpoints(pid: str) -> None:
    print("\n=== Trying common API path patterns ===")
    patterns = [
        f"https://www.openicpsr.org/openicpsr/project/{pid}/showStats",
        f"https://www.openicpsr.org/openicpsr/project/{pid}/stats",
        f"https://www.openicpsr.org/openicpsr/project/{pid}/metrics",
        f"https://www.openicpsr.org/openicpsr/project/{pid}/version/V1/showStats",
        f"https://www.openicpsr.org/openicpsr/project/{pid}/version/V1/stats",
        f"https://www.openicpsr.org/openicpsr/api/project/{pid}/stats",
        f"https://www.openicpsr.org/api/project/{pid}/stats",
        f"https://www.openicpsr.org/openicpsr/project/{pid}/downloadCount",
        f"https://pcms.icpsr.umich.edu/pcms/metrics/data/api/downloadCount?studyId={pid}&startDt=01/01/2020&endDt=04/28/2026",
    ]
    for url in patterns:
        try:
            r = SCRAPER.get(url, headers=HEADERS, timeout=20, allow_redirects=False)
        except Exception as e:
            print(f"  ERROR  {url}\n         {e}")
            continue
        ct = r.headers.get("Content-Type", "")
        print(f"  {r.status_code} ({len(r.text):>6,}b, {ct[:30]:<30}) {url}")
        if r.status_code == 200 and ("json" in ct.lower() or r.text.lstrip().startswith(("{", "["))):
            try:
                data = r.json()
                print(f"    -> JSON: {json.dumps(data, indent=2)[:400]}")
            except Exception:
                pass


def fetch_project_usage_js() -> None:
    """
    The openICPSR page loads ProjectUsage.js, which is the JS file that
    actually fetches and renders the download stats. Pull it down and dump
    every URL/endpoint pattern it references.
    """
    print("\n=== Fetching ProjectUsage.js to find the real stats endpoint ===")
    js_url = "https://pcms.icpsr.umich.edu/pcms/resources/js/app/projectUsage/ProjectUsage.js"
    try:
        r = SCRAPER.get(js_url, headers=HEADERS, timeout=30)
    except Exception as e:
        print(f"  ERROR fetching: {e}")
        return
    print(f"  HTTP {r.status_code}, len: {len(r.text):,}")
    if r.status_code != 200:
        return

    js = r.text

    # Pull every URL, ajax(), $.get/post, fetch(), and quoted path that looks
    # like an API endpoint.
    print("\n  --- URL-shaped strings ---")
    seen = set()
    for m in re.finditer(r'["\']((?:https?:)?/[^"\'\s<>]{4,200})["\']', js):
        url = m.group(1)
        if any(url.lower().endswith(ext) for ext in
               (".css", ".js", ".png", ".jpg", ".svg", ".gif", ".woff", ".woff2", ".ttf")):
            continue
        seen.add(url)
    for c in sorted(seen):
        print(f"    {c}")

    print("\n  --- $.ajax / $.get / $.post / fetch( / axios. snippets ---")
    for m in re.finditer(
        r"(?:\$\.(?:ajax|get|post|getJSON)\s*\(|fetch\s*\(|axios\.\w+\s*\()[^;]{0,400}",
        js,
    ):
        snippet = m.group(0)
        # Trim and indent
        snippet = re.sub(r"\s+", " ", snippet).strip()
        print(f"    {snippet[:300]}")

    # Save the full JS so we can inspect URL construction logic
    with open("ProjectUsage.js", "w", encoding="utf-8") as f:
        f.write(js)
    print("\n  [Saved full ProjectUsage.js for inspection]")


def find_react_props(html: str) -> None:
    """Look in the project page HTML for the values of tenant / level / pcmsURL
    passed to the ProjectUsage React component."""
    print("\n=== Looking for React component props in page HTML ===")
    keys = ("pcmsURL", "tenant", "level", "projectId", "selectedPath")
    for key in keys:
        # Match: key="value" or key: "value" or key='value' or 'key':'value'
        for m in re.finditer(rf'["\']?{key}["\']?\s*[:=]\s*["\']([^"\']{{1,80}})["\']', html, re.I):
            print(f"  {key} = {m.group(1)!r}")
            break
        else:
            print(f"  {key} = (not found)")


def test_usage_endpoints(pid: str) -> None:
    """Try the URL pattern from ProjectUsage.js with plausible tenant/level values."""
    print("\n=== Testing the usage/view endpoint (the real one) ===")
    base = "https://pcms.icpsr.umich.edu/pcms/metrics/data/api"
    candidates = [
        f"{base}/openicpsr/projects/{pid}/usage/view?level=project",
        f"{base}/openicpsr/projects/{pid}/usage/view?level=overall",
        f"{base}/openicpsr/projects/{pid}/usage/view",
        f"{base}/openICPSR/projects/{pid}/usage/view?level=project",
        f"{base}/icpsr/projects/{pid}/usage/view?level=project",
        f"{base}/projects/{pid}/usage/view?level=project",
        f"{base}/studies/{pid}/usage/view?level=project",
        f"{base}/openicpsr/projects/{pid}/usage/download?format=csv",
        f"{base}/studies/{pid}/usage/download?format=csv",
    ]
    for url in candidates:
        try:
            r = SCRAPER.get(url, headers=HEADERS, timeout=20, allow_redirects=False)
        except Exception as e:
            print(f"  ERROR  {url}\n         {e}")
            continue
        ct = r.headers.get("Content-Type", "")
        body_preview = r.text[:120].replace("\n", " ")
        print(f"  {r.status_code} ({len(r.text):>6,}b, {ct[:30]:<30}) {url}")
        if r.status_code == 200 and r.text.strip():
            print(f"    body: {body_preview}")


def main():
    html = fetch_page()
    grep_visible_numbers(html)
    grep_patterns(html)
    grep_inline_scripts(html)
    try_direct_endpoints(PROJECT_ID)
    fetch_project_usage_js()
    find_react_props(html)
    test_usage_endpoints(PROJECT_ID)


if __name__ == "__main__":
    import contextlib
    import traceback

    log_path = f"probe_{PROJECT_ID}.txt"
    print(f"Running probe for {PROJECT_ID}, writing output to {log_path}...")

    with open(log_path, "w", encoding="utf-8") as f:
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            try:
                main()
            except Exception:
                traceback.print_exc()

    print(f"Done. Output saved to {log_path}")
