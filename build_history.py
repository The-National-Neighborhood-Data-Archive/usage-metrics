#!/usr/bin/env python3
"""
Build a running month-by-month download history for curated ICPSR
studies from every saved time-series snapshot.

ICPSR keeps a rolling three-year window of download history and trims its
oldest months in batches (the first trim showed up in the 2026-08-01
scrape, when everything before July 2023 disappeared). Totals summed from
what ICPSR currently serves shrink at every trim. The repo saves every
monthly scrape, so this script combines them: months ICPSR no longer
reports keep their last saved value.

Newest wins. For each (study_id, year, month), keep the value from the
newest dated snapshot that contains it. A later scrape is the better
measurement of a month ICPSR still serves (it supersedes partial-month
counts from mid-month runs), and a month ICPSR has dropped keeps the value
from the last snapshot that served it. Never take the max across
snapshots.

Reads:
  data/nanda_usage_timeseries_YYYY-MM-DD.csv  (strict-pattern files only;
                                               _latest is ignored)
  data/nanda_download_history.csv             (the previous output, read as
                                               one more source so history
                                               survives a dated file going
                                               missing)

Writes:
  data/nanda_download_history.csv

The dated snapshot files are the archive of record: never prune them.
build_dashboard.py and generate_delta.py import the helpers below;
build_history(cutoff=...) reproduces the history as it stood on an
earlier snapshot date.
"""

import re
from datetime import date
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
# Deliberately matches neither the nanda_usage_stats_* nor the
# nanda_usage_timeseries_* globs the other scripts use.
HISTORY_CSV_NAME = "nanda_download_history.csv"
HISTORY_CSV = DATA_DIR / HISTORY_CSV_NAME
TIMESERIES_DATED_RE = re.compile(r"^nanda_usage_timeseries_(\d{4}-\d{2}-\d{2})\.csv$")

KEY = ["study_id", "year", "month"]
COUNT_COLUMNS = ["data_downloads", "documentation_downloads", "total_downloads"]
HISTORY_COLUMNS = KEY + COUNT_COLUMNS + ["source_snapshot", "in_latest_snapshot"]


def find_timeseries_snapshots(data_dir: Path = DATA_DIR):
    """Return (iso_date, path) for every dated time-series file, oldest first."""
    files = []
    for f in Path(data_dir).glob("nanda_usage_timeseries_*.csv"):
        m = TIMESERIES_DATED_RE.match(f.name)
        if m:
            files.append((m.group(1), f))
    files.sort(key=lambda x: x[0])
    return files


def read_snapshot(path: Path, snapshot_date: str) -> pd.DataFrame:
    """One dated time-series file as history rows. The snapshot date comes
    from the filename, not the `timestamp` column."""
    df = pd.read_csv(path, usecols=KEY + COUNT_COLUMNS)
    df = df.astype({c: int for c in KEY + COUNT_COLUMNS})
    df["source_snapshot"] = snapshot_date
    return df


def read_history(path: Path = HISTORY_CSV):
    """Load a saved history CSV, or return None if there isn't one."""
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"source_snapshot": str})
    df = df[HISTORY_COLUMNS].astype({c: int for c in KEY + COUNT_COLUMNS})
    return df


def build_history(data_dir: Path = DATA_DIR, cutoff=None) -> pd.DataFrame:
    """
    Combine every dated time-series snapshot, plus the saved history file,
    into one row per (study_id, year, month). Newest snapshot wins.

    cutoff: ISO date (YYYY-MM-DD). Only snapshots dated on or before it
    count, which reproduces the history as it stood on that date.

    Returns HISTORY_COLUMNS sorted by study_id, year, month.
    `in_latest_snapshot` is True where the newest snapshot considered still
    contains that month.
    """
    data_dir = Path(data_dir)
    if cutoff is not None:
        cutoff = date.fromisoformat(str(cutoff)).isoformat()

    frames, snapshot_dates = [], []
    for snap_date, path in find_timeseries_snapshots(data_dir):
        if cutoff is not None and snap_date > cutoff:
            continue
        snapshot_dates.append(snap_date)
        frames.append(read_snapshot(path, snap_date).assign(_from_dated_file=True))

    # Safety net: the previous output still holds months whose dated source
    # file has gone missing. The dated files are the archive of record, so
    # an unreadable history file (a botched merge, say) is skipped with a
    # warning rather than stopping the monthly run.
    try:
        prior = read_history(data_dir / HISTORY_CSV_NAME)
    except (ValueError, KeyError) as e:
        reason = " ".join(str(e).split())[:200]
        print(f"::warning title=Download history unreadable::{HISTORY_CSV_NAME} "
              f"could not be read ({reason}); rebuilt from dated snapshots only")
        prior = None
    if prior is not None:
        prior = prior.drop(columns="in_latest_snapshot")
        if cutoff is not None:
            prior = prior[prior["source_snapshot"] <= cutoff]
        snapshot_dates.extend(prior["source_snapshot"].unique())
        frames.append(prior.assign(_from_dated_file=False))

    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=HISTORY_COLUMNS).astype(
            {**{c: int for c in KEY + COUNT_COLUMNS}, "in_latest_snapshot": bool}
        )

    combined = pd.concat(frames, ignore_index=True)
    # Newest snapshot wins; on a tie, the dated file beats the saved history.
    combined = combined.sort_values(["source_snapshot", "_from_dated_file"])
    history = combined.drop_duplicates(KEY, keep="last")
    history = history.assign(in_latest_snapshot=history["source_snapshot"] == max(snapshot_dates))
    return history.sort_values(KEY)[HISTORY_COLUMNS].reset_index(drop=True)


def apply_history_totals(stats: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """
    Copy of a usage-stats frame whose `total_downloads` is the history sum
    for every study with history rows. Studies without history (openICPSR,
    RDE, curated studies PCMS serves no monthly buckets for) keep their
    reported totals.
    """
    sums = history.groupby("study_id")["total_downloads"].sum()
    out = stats.copy()
    has_history = out["study_id"].isin(sums.index)
    out.loc[has_history, "total_downloads"] = out.loc[has_history, "study_id"].map(sums)
    return out


def preserved_downloads(history: pd.DataFrame, study_ids=None) -> int:
    """
    Downloads from months ICPSR no longer reports: history rows missing from
    the newest snapshot that served each study. Measured per study, so a
    study whose time-series request failed in the latest scrape doesn't get
    its still-served months counted as dropped. `study_ids` limits the count
    to those studies (the ones a report actually shows).
    """
    if study_ids is not None:
        history = history[history["study_id"].isin(study_ids)]
    newest = history.groupby("study_id")["source_snapshot"].transform("max")
    return int(history.loc[history["source_snapshot"] < newest, "total_downloads"].sum())


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    history = build_history(DATA_DIR)
    history.to_csv(HISTORY_CSV, index=False)
    if history.empty:
        print(f"Wrote {HISTORY_CSV}: no dated time-series snapshots found")
        return
    months = history["year"] * 100 + history["month"]
    first, last = int(months.min()), int(months.max())
    print(f"Wrote {HISTORY_CSV}: {len(history):,} rows, "
          f"{history['study_id'].nunique()} studies, "
          f"{first // 100}-{first % 100:02d} to {last // 100}-{last % 100:02d}, "
          f"{preserved_downloads(history):,} downloads preserved from months "
          f"ICPSR no longer reports")


if __name__ == "__main__":
    main()
