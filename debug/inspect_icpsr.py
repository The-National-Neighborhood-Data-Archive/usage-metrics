#!/usr/bin/env python3
"""
Inspect a NaNDA study page via its DOI so we can see exactly where to grab
title, downloads, publications, and status.

DOI patterns:
  - Curated ICPSR (5-digit id): https://doi.org/10.3886/ICPSR{id}
  - openICPSR (6-digit id):     https://doi.org/10.3886/E{id}

Run:
    python inspect_icpsr.py                # defaults to ICPSR 38567
    python inspect_icpsr.py 38567          # curated, by id
    python inspect_icpsr.py E237305        # openICPSR, by id (with E prefix)
    python inspect_icpsr.py https://doi.org/10.3886/ICPSR38567   # full URL

Paste the full output back to Claude.
"""

import re
import sys
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 NaNDA-inspect/1.0"}


def build_url(arg: str) -> str:
    arg = arg.strip()
    if arg.startswith("http"):
        return arg
    if arg.upper().startswith("E"):
        return f"https://doi.org/10.3886/{arg.upper()}"
    if arg.upper().startswith("ICPSR"):
        return f"https://doi.org/10.3886/{arg.upper()}"
    # bare id: assume curated
    return f"https://doi.org/10.3886/ICPSR{arg}"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "38567"
    start_url = build_url(arg)
    print(f"=== Starting URL: {start_url} ===\n")

    r = requests.get(start_url, headers=HEADERS, timeout=30, allow_redirects=True)
    print(f"HTTP {r.status_code}, len: {len(r.text):,}")
    print(f"Final URL after redirects: {r.url}\n")

    if r.history:
        print("Redirect chain:")
        for h in r.history:
            print(f"  {h.status_code} {h.url}")
        print(f"  -> {r.status_code} {r.url}\n")

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    # --- Title ---
    print("--- Title candidates ---")
    if soup.title:
        print(f"  <title>: {soup.title.get_text(strip=True)!r}")
    for sel in [("h1", "study-title"), ("h1", None), ("h2", None)]:
        tag, cls = sel
        el = soup.find(tag, class_=cls) if cls else soup.find(tag)
        if el:
            txt = el.get_text(" ", strip=True)
            label = f"{tag}.{cls}" if cls else tag
            print(f"  {label}: {txt[:200]!r}")

    # --- studyMetrics div (curated ICPSR pattern) ---
    print("\n--- div#studyMetrics ---")
    metrics = soup.find("div", id="studyMetrics")
    if metrics:
        html = str(metrics)
        print(html[:2500])
        if len(html) > 2500:
            print(f"  ... ({len(html) - 2500} more chars)")
    else:
        print("  <not found>")

    # --- statNum / statLabel (openICPSR pattern) ---
    print("\n--- .statNum / .statLabel pairs ---")
    nums = soup.find_all(class_="statNum")
    labels = soup.find_all(class_="statLabel")
    if nums or labels:
        print(f"  found {len(nums)} statNum, {len(labels)} statLabel")
        for i, n in enumerate(nums[:6]):
            label = labels[i].get_text(strip=True) if i < len(labels) else "?"
            print(f"    {n.get_text(strip=True)!r:>15}  <- {label!r}")
    else:
        print("  <not found>")

    # --- Visible numbers near keywords ---
    print("\n--- Visible numbers near 'Downloads'/'Publications'/'Citations' ---")
    for kw in ("Downloads", "Publications", "Citations", "Total Downloads"):
        pattern = rf"(?:{kw}[^\n]{{0,80}}?[\d,]+|[\d,]+[^\n]{{0,40}}?{kw})"
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            for m in matches[:3]:
                print(f"  {kw}: {m.strip()[:120]!r}")
        else:
            print(f"  {kw}: <no nearby number found>")

    # --- Status / badge hints ---
    print("\n--- Status / badge hints ---")
    for kw in ("Curated", "Published", "Beta", "Restricted", "Self-published"):
        if kw in text:
            idx = text.find(kw)
            print(f"  '{kw}' at idx {idx}: ...{text[max(0,idx-40):idx+50]}...")

    # --- Inline JSON-like script tags ---
    print("\n--- Inline JSON-ish script tags (full content) ---")
    for s in soup.find_all("script"):
        t = s.get("type", "")
        sid_attr = s.get("id", "")
        if sid_attr or "json" in t.lower():
            content = s.string or ""
            print(f"\n  script id={sid_attr!r} type={t!r} len={len(content)}")
            print("  --- begin content ---")
            # Print full content; will be saved to file too
            print(content)
            print("  --- end content ---")


if __name__ == "__main__":
    import io
    # Tee stdout: print to console AND save to inspect_<arg>.txt so nothing scrolls away
    arg = sys.argv[1] if len(sys.argv) > 1 else "38567"
    safe = re.sub(r"[^A-Za-z0-9]+", "_", arg)
    log_path = f"inspect_{safe}.txt"

    class Tee:
        def __init__(self, *streams): self.streams = streams
        def write(self, s):
            for x in self.streams: x.write(s)
        def flush(self):
            for x in self.streams: x.flush()

    real_stdout = sys.stdout
    with open(log_path, "w", encoding="utf-8") as f:
        sys.stdout = Tee(real_stdout, f)
        try:
            main()
        finally:
            sys.stdout = real_stdout
    print(f"\n[Saved full output to {log_path}]")
