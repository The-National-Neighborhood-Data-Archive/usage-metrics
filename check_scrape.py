"""
Sanity check a new scrape against the previous one before it reaches the
download history or the public dashboard.

Background: on 2026-11-01 ICPSR answered every request from the GitHub
Actions runner with HTTP 403. The scraper wrote zeros, the pipeline published
them, and the dashboard showed -15,561 downloads. See
diagnosis-2026-11-empty-scrape.md.

The check fails if any of these is true:

  1. More than 25% of studies with a nonzero total in the previous scrape
     now report 0 or are missing.
  2. The curated monthly time-series has no rows for the most recent
     complete month (the calendar month before the scrape date).
  3. Curated unique users sum to 0 when the previous scrape's sum was above 0.

An ICPSR history trim (see diagnosis-2026-08-negative-deltas.md) lowers
totals and unique users but leaves them nonzero and keeps the latest month,
so it passes all three.

Usage:
    python check_scrape.py                 # newest dated snapshot vs the one before
    python check_scrape.py --quarantine    # same, and on failure move the new
                                           # dated files to data/quarantine/<date>/
    python check_scrape.py --stats data/quarantine/2026-11-01/nanda_usage_stats_2026-11-01.csv \\
        --prev-stats data/nanda_usage_stats_2026-10-01.csv

Exit code 0 = pass, 1 = fail.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
QUARANTINE_DIR = DATA_DIR / "quarantine"

# Same strict pattern generate_delta.py and build_dashboard.py use.
STATS_DATED_RE = re.compile(r"^nanda_usage_stats_(\d{4}-\d{2}-\d{2})\.csv$")

MAX_ZEROED_SHARE = 0.25


def dated_stats_files(data_dir: Path = DATA_DIR):
    """Dated snapshot files in the top level of data_dir, oldest first."""
    out = []
    for f in Path(data_dir).glob("nanda_usage_stats_*.csv"):
        m = STATS_DATED_RE.match(f.name)
        if m:
            out.append((m.group(1), f))
    return sorted(out)


def snapshot_date(path: Path) -> str:
    m = STATS_DATED_RE.match(Path(path).name)
    if not m:
        sys.exit(f"Can't read a date from {path}; expected nanda_usage_stats_YYYY-MM-DD.csv")
    return m.group(1)


def timeseries_for(stats_path: Path) -> Path:
    """The time-series file written by the same run, in the same folder."""
    date = snapshot_date(stats_path)
    return Path(stats_path).parent / f"nanda_usage_timeseries_{date}.csv"


def previous_complete_month(date: str):
    year, month = int(date[:4]), int(date[5:7])
    return (year - 1, 12) if month == 1 else (year, month - 1)


def check(new_stats: Path, new_ts: Path, prev_stats: Path) -> list:
    """Return a list of failure messages (empty = pass)."""
    failures = []
    new = pd.read_csv(new_stats)
    prev = pd.read_csv(prev_stats)
    date = snapshot_date(new_stats)

    # 1. Studies that had downloads and now show 0 or are missing.
    prev_nonzero = prev.loc[prev["total_downloads"].fillna(0) > 0, "study_id"]
    new_totals = new.set_index("study_id")["total_downloads"].fillna(0)
    zeroed = [sid for sid in prev_nonzero if new_totals.get(sid, 0) == 0]
    share = len(zeroed) / len(prev_nonzero) if len(prev_nonzero) else 0.0
    print(f"Studies with downloads last time that now show 0 or are missing: "
          f"{len(zeroed)} of {len(prev_nonzero)} ({share:.0%}; limit {MAX_ZEROED_SHARE:.0%})")
    if share > MAX_ZEROED_SHARE:
        failures.append(f"{len(zeroed)} of {len(prev_nonzero)} studies dropped to 0 or went missing")

    # 2. Most recent complete month present in the curated time-series.
    year, month = previous_complete_month(date)
    if new_ts.exists():
        ts = pd.read_csv(new_ts)
        n_rows = int(((ts["year"] == year) & (ts["month"] == month)).sum())
    else:
        n_rows = 0
    print(f"Time-series rows for {year}-{month:02d}: {n_rows} ({new_ts})")
    if n_rows == 0:
        failures.append(f"time-series has no rows for {year}-{month:02d}")

    # 3. Curated unique users.
    new_users = new["unique_users"].fillna(0).sum()
    prev_users = prev["unique_users"].fillna(0).sum()
    print(f"Curated unique users: {new_users:,.0f} (previous {prev_users:,.0f})")
    if new_users == 0 and prev_users > 0:
        failures.append("curated unique users dropped to 0")

    return failures


def quarantine(new_stats: Path) -> Path:
    """Move this run's dated stats and time-series files to data/quarantine/<date>/."""
    date = snapshot_date(new_stats)
    dest = QUARANTINE_DIR / date
    dest.mkdir(parents=True, exist_ok=True)
    for f in (Path(new_stats), timeseries_for(new_stats)):
        if f.exists():
            shutil.move(str(f), str(dest / f.name))
            print(f"Moved {f} -> {dest / f.name}")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stats", type=Path, help="new snapshot (default: newest dated file in data/)")
    ap.add_argument("--timeseries", type=Path, help="new time-series (default: same date and folder as --stats)")
    ap.add_argument("--prev-stats", type=Path, help="previous snapshot (default: second-newest dated file in data/)")
    ap.add_argument("--quarantine", action="store_true",
                    help="on failure, move the new dated files to data/quarantine/<date>/")
    args = ap.parse_args()

    files = dated_stats_files()
    new_stats = args.stats or (files[-1][1] if files else None)
    if args.prev_stats:
        prev_stats = args.prev_stats
    else:
        older = [f for d, f in files if Path(f).resolve() != Path(new_stats).resolve()]
        prev_stats = older[-1] if older else None
    if new_stats is None or prev_stats is None:
        print("Need two dated snapshots to compare; skipping check.")
        return 0
    new_ts = args.timeseries or timeseries_for(new_stats)

    print(f"New scrape:      {new_stats}")
    print(f"Previous scrape: {prev_stats}")
    failures = check(new_stats, new_ts, prev_stats)

    if not failures:
        print("PASS")
        return 0

    print("FAIL")
    for msg in failures:
        print(f"  - {msg}")
    if args.quarantine:
        quarantine(new_stats)
    return 1


if __name__ == "__main__":
    sys.exit(main())
