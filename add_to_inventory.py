#!/usr/bin/env python3
"""
add_to_inventory.py — safely append a new NaNDA dataset to inventory.csv.

Usage:
    python add_to_inventory.py <study_id> --archive {ICPSR|openICPSR}
                              [--deposit-via {legacy|RDE}]
                              [--dry-run] [--force]

Fetches title / version / version_date / DOI from public ICPSR sources, runs
strict validation gates, and appends a row to inventory.csv. Never commits
or pushes — prints the git commands for the operator to run after eyeballing
the row.

Metadata sources (chosen by reliability):

  1. DataCite REST API (api.datacite.org/dois/{doi}) — primary. ICPSR mints
     DOIs at publication, so this is fresh on day-zero releases. Endpoint
     returns title, version, `created` timestamp (matches inventory
     version_date for both archives in spot-checks), and confirms the DOI
     resolves. Free, no auth, returns structured JSON.

  2. ICPSR public study page JSON-LD — fallback for curated ICPSR
     (`https://www.icpsr.umich.edu/web/ICPSR/studies/{id}`). Inline
     `<script type="application/ld+json">` carries name, version,
     dateModified, and identifier.value (DOI).

  3. openICPSR project page JSON-LD — fallback for openICPSR
     (`https://www.openicpsr.org/openicpsr/project/{id}/view`). Same JSON-LD
     shape, but only ever exposes the V1 metadata even when newer minor
     versions exist; treat with care for late updates.

The other endpoints considered and rejected:
  - ICPSR search API (`search.icpsr.umich.edu/.../studies`) — already used
    by the monthly scraper for publication counts but returns 0 results
    for fresh study IDs; not useful at first-publication moment.
  - The new ICPSR sites pages (`/sites/icpsr/view/studies/{id}`) are a
    Next.js app with no useful HTML payload — content is hydrated
    client-side. Skipped.

Constraints:
  - Append-only. Use --force to overwrite a duplicate study_id (typo fix).
  - Status is always 'published' — this helper is only used post-release.
  - HTTP failures → exit non-zero, write nothing.
  - Validation gate failure → exit non-zero, write nothing.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import cloudscraper
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INVENTORY_PATH = Path(__file__).parent / "inventory.csv"

NANDA_PREFIX = "National Neighborhood Data Archive (NaNDA):"

CSV_COLUMNS = [
    "study_id", "archive", "deposit_via", "status", "title",
    "version", "version_date", "doi", "url",
]

DATACITE_DOI_URL = "https://api.datacite.org/dois/{doi}"
ICPSR_STUDY_URL = "https://www.icpsr.umich.edu/web/ICPSR/studies/{id}"
OPENICPSR_PROJECT_URL = "https://www.openicpsr.org/openicpsr/project/{id}/view"
LANDING_URL = "https://www.icpsr.umich.edu/sites/icpsr/view/studies/{id}"

HTTP_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iso_to_slash_date(iso_date: str) -> str:
    """'2024-10-14' (or '2024-10-14T14:03:22.000Z') → '10/14/2024'."""
    if not iso_date:
        return ""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", iso_date)
    if not m:
        return iso_date
    y, mo, d = m.group(1), str(int(m.group(2))), str(int(m.group(3)))
    return f"{mo}/{d}/{y}"


def construct_candidate_dois(study_id: int, archive: str) -> list:
    """First-publication DOI guesses, ordered by likelihood."""
    if archive == "ICPSR":
        return [f"10.3886/ICPSR{study_id}.v1"]
    # openICPSR: bare 'V1' is the first-deposit form; the 'V10' style appears
    # only when a minor version exists. Try both.
    return [f"10.3886/E{study_id}V1", f"10.3886/E{study_id}V10"]


def fetch_datacite(doi: str) -> dict | None:
    """Return DataCite attributes for `doi`, or None on 404."""
    r = requests.get(
        DATACITE_DOI_URL.format(doi=doi),
        timeout=HTTP_TIMEOUT,
        headers={"Accept": "application/vnd.api+json"},
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("data", {}).get("attributes", {})


def parse_datacite(attrs: dict, doi: str) -> dict:
    """DataCite attributes → row dict (title, version, version_date, doi)."""
    titles = attrs.get("titles") or []
    title = titles[0].get("title", "") if titles else ""
    version = attrs.get("version") or ""
    # Normalize 'v1' → 'V1', '1.0' → 'V1.0'.
    if version:
        if version[0] in ("v", "V"):
            version = "V" + version[1:]
        else:
            version = "V" + version
    created = attrs.get("created") or ""
    return {
        "title": title,
        "version": version,
        "version_date": iso_to_slash_date(created),
        "doi": doi,
    }


def fetch_json_ld(url: str) -> dict | None:
    """Pull the first JSON-LD block from `url`; None if page is missing/empty."""
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.headers.update({
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    r = scraper.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    m = re.search(
        r'<script type="application/ld\+json">\s*(\{.+?\})\s*</script>',
        r.text, re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parse_json_ld(ld: dict) -> dict:
    """JSON-LD dict → row dict (title, version, version_date, doi)."""
    title = ld.get("name", "")
    version = ld.get("version", "") or ""
    # ICPSR curated emits dateModified for version date; openICPSR omits it
    # and only carries datePublished (which is the original deposit date).
    date_iso = ld.get("dateModified") or ld.get("datePublished") or ""
    ident = ld.get("identifier") or {}
    raw_doi = ident.get("value", "") if isinstance(ident, dict) else ""
    doi = raw_doi.removeprefix("doi:") if raw_doi else ""
    return {
        "title": title,
        "version": version,
        "version_date": iso_to_slash_date(date_iso),
        "doi": doi,
    }


def fetch_metadata(study_id: int, archive: str) -> dict:
    """Try DataCite first, then the archive's public page. Returns row dict
    with title/version/version_date/doi. Raises on total failure.
    """
    errors = []

    # 1. DataCite (primary).
    for doi in construct_candidate_dois(study_id, archive):
        try:
            attrs = fetch_datacite(doi)
        except requests.RequestException as e:
            errors.append(f"datacite {doi}: {e}")
            continue
        if attrs:
            return parse_datacite(attrs, doi)

    # 2. Archive page JSON-LD (fallback).
    page_url = (ICPSR_STUDY_URL if archive == "ICPSR" else OPENICPSR_PROJECT_URL)
    page_url = page_url.format(id=study_id)
    try:
        ld = fetch_json_ld(page_url)
    except requests.RequestException as e:
        errors.append(f"page {page_url}: {e}")
        ld = None

    if ld:
        out = parse_json_ld(ld)
        if out["doi"]:
            return out
        errors.append(f"page {page_url}: JSON-LD has no DOI")
    else:
        errors.append(f"page {page_url}: no JSON-LD block")

    raise RuntimeError("metadata fetch failed: " + "; ".join(errors))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VERSION_RE = re.compile(r"^V\d+(\.\d+)?$")
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
URL_PREFIXES = ("https://www.icpsr.umich.edu/", "https://www.openicpsr.org/")
TITLE_PREFIX = "National Neighborhood Data Archive (NaNDA):"


def validate_row(row: dict) -> list:
    """Return a list of validation-failure messages (empty if all pass)."""
    errs = []
    title = row.get("title") or ""
    if not title.startswith(TITLE_PREFIX):
        errs.append(f"title must start with {TITLE_PREFIX!r}; got {title[:80]!r}")
    if row.get("archive") not in {"ICPSR", "openICPSR"}:
        errs.append(f"archive must be 'ICPSR' or 'openICPSR'; got {row.get('archive')!r}")
    if row.get("deposit_via") not in {"legacy", "RDE"}:
        errs.append(f"deposit_via must be 'legacy' or 'RDE'; got {row.get('deposit_via')!r}")
    if not VERSION_RE.match(row.get("version") or ""):
        errs.append(f"version must match V<n>[.<m>]; got {row.get('version')!r}")
    if not DATE_RE.match(row.get("version_date") or ""):
        errs.append(f"version_date must match M/D/YYYY; got {row.get('version_date')!r}")
    if not (row.get("doi") or "").startswith("10.3886/"):
        errs.append(f"doi must start with '10.3886/'; got {row.get('doi')!r}")
    url = row.get("url") or ""
    if not any(url.startswith(p) for p in URL_PREFIXES):
        errs.append(f"url must start with one of {URL_PREFIXES}; got {url!r}")
    return errs


# ---------------------------------------------------------------------------
# Inventory I/O
# ---------------------------------------------------------------------------

def load_inventory(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8", dtype={"study_id": int})


def write_inventory(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8")


def build_row(study_id: int, archive: str, deposit_via: str, meta: dict) -> dict:
    return {
        "study_id": study_id,
        "archive": archive,
        "deposit_via": deposit_via,
        "status": "published",
        "title": meta["title"],
        "version": meta["version"],
        "version_date": meta["version_date"],
        "doi": meta["doi"],
        "url": LANDING_URL.format(id=study_id),
    }


def format_row_preview(row: dict) -> str:
    width = max(len(k) for k in row)
    return "\n".join(f"  {k:<{width}}  {row[k]}" for k in CSV_COLUMNS)


def title_snippet(title: str, max_len: int = 60) -> str:
    body = title.removeprefix(TITLE_PREFIX).strip(" :")
    if len(body) > max_len:
        body = body[: max_len - 3].rstrip() + "..."
    return body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("study_id", type=int, help="ICPSR or openICPSR study/project ID")
    p.add_argument("--archive", required=True, choices=["ICPSR", "openICPSR"],
                   help="Which archive the dataset lives in")
    p.add_argument("--deposit-via", default="RDE", choices=["legacy", "RDE"],
                   help="Deposit pathway (default: RDE — the standard for "
                        "all new deposits; legacy is for pre-RDE backfills)")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch and print the row; do not modify inventory.csv")
    p.add_argument("--force", action="store_true",
                   help="Replace an existing row for the same study_id")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    inv_path = INVENTORY_PATH
    df = load_inventory(inv_path)
    existing_idx = df.index[df["study_id"] == args.study_id].tolist()

    if existing_idx and not args.force and not args.dry_run:
        existing = df.loc[existing_idx[0]].to_dict()
        print(f"ERROR: study_id {args.study_id} already in inventory.csv. "
              f"Re-run with --force to overwrite.", file=sys.stderr)
        print("Existing row:", file=sys.stderr)
        print(format_row_preview(existing), file=sys.stderr)
        return 2

    try:
        meta = fetch_metadata(args.study_id, args.archive)
    except (requests.RequestException, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    row = build_row(args.study_id, args.archive, args.deposit_via, meta)
    errs = validate_row(row)
    if errs:
        print("ERROR: validation failed:", file=sys.stderr)
        for msg in errs:
            print(f"  - {msg}", file=sys.stderr)
        print("Fetched row:", file=sys.stderr)
        print(format_row_preview(row), file=sys.stderr)
        print("\nHand-edit inventory.csv if the source metadata is correct "
              "but doesn't match the validators.", file=sys.stderr)
        return 4

    print("Row to add:")
    print(format_row_preview(row))

    if args.dry_run:
        print("\n[dry-run] inventory.csv was not modified.")
        return 0

    new_df = pd.DataFrame([row], columns=CSV_COLUMNS)
    if existing_idx:
        df.loc[existing_idx[0]] = new_df.iloc[0]
        out_df = df
        action = "replaced"
    else:
        out_df = pd.concat([df, new_df], ignore_index=True)
        action = "appended"

    write_inventory(out_df, inv_path)

    # Sanity-check round-trip.
    check_df = load_inventory(inv_path)
    if len(check_df) != len(out_df):
        print("ERROR: inventory.csv re-read row count mismatch "
              f"(wrote {len(out_df)}, read {len(check_df)})", file=sys.stderr)
        return 5
    if (check_df["study_id"] == args.study_id).sum() != 1:
        print(f"ERROR: study_id {args.study_id} appears "
              f"{(check_df['study_id'] == args.study_id).sum()} times after write",
              file=sys.stderr)
        return 5

    snippet = title_snippet(row["title"])
    print(f"\n{action.title()} row in {inv_path.name}.")
    print("\nNext steps:")
    print("  cd usage-metrics")
    print("  git add inventory.csv")
    print(f"  git commit -m \"Add {snippet} ({args.study_id}) to inventory\"")
    print("  git push")
    return 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())
