"""Tests for build_history.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import build_history as bh  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_snapshot(data_dir: Path, snap_date: str, rows, name: str | None = None) -> Path:
    """Write a time-series CSV shaped like the scraper's output. `rows` are
    (study_id, year, month, data_downloads, documentation_downloads)."""
    df = pd.DataFrame(rows, columns=["study_id", "year", "month",
                                     "data_downloads", "documentation_downloads"])
    df["total_downloads"] = df["data_downloads"] + df["documentation_downloads"]
    df["timestamp"] = f"{snap_date} 09:00:00"
    path = data_dir / (name or f"nanda_usage_timeseries_{snap_date}.csv")
    df.to_csv(path, index=False)
    return path


def save_history(data_dir: Path) -> None:
    bh.build_history(data_dir).to_csv(data_dir / bh.HISTORY_CSV_NAME, index=False)


def get_row(history: pd.DataFrame, study_id: int, year: int, month: int) -> pd.Series:
    match = history[(history["study_id"] == study_id)
                    & (history["year"] == year)
                    & (history["month"] == month)]
    assert len(match) == 1, f"expected one row for {study_id} {year}-{month:02d}"
    return match.iloc[0]


# ---------------------------------------------------------------------------
# build_history
# ---------------------------------------------------------------------------

def test_newest_wins_when_snapshots_overlap(tmp_path):
    # May 12 caught a partial May; June 1 re-served the full month and
    # revised April down. Newest wins in both directions (never the max).
    write_snapshot(tmp_path, "2026-05-12", [(1, 2026, 4, 12, 8), (1, 2026, 5, 2, 1)])
    write_snapshot(tmp_path, "2026-06-01", [(1, 2026, 4, 10, 5), (1, 2026, 5, 7, 4)])
    history = bh.build_history(tmp_path)

    assert len(history) == 2
    april = get_row(history, 1, 2026, 4)
    may = get_row(history, 1, 2026, 5)
    assert april["total_downloads"] == 15
    assert (may["data_downloads"], may["documentation_downloads"], may["total_downloads"]) == (7, 4, 11)
    assert set(history["source_snapshot"]) == {"2026-06-01"}
    assert history["in_latest_snapshot"].all()


def test_dropped_month_keeps_last_value(tmp_path):
    # ICPSR trims June 2023 between the July and August scrapes.
    write_snapshot(tmp_path, "2026-07-01", [(1, 2023, 6, 30, 10), (1, 2023, 7, 5, 5)])
    write_snapshot(tmp_path, "2026-08-01", [(1, 2023, 7, 6, 5), (1, 2026, 7, 1, 1)])
    history = bh.build_history(tmp_path)

    june = get_row(history, 1, 2023, 6)
    assert june["total_downloads"] == 40
    assert june["source_snapshot"] == "2026-07-01"
    assert not june["in_latest_snapshot"]
    assert get_row(history, 1, 2023, 7)["in_latest_snapshot"]
    assert get_row(history, 1, 2026, 7)["in_latest_snapshot"]
    # The months still served add up to what the latest snapshot reports.
    assert history.loc[history["in_latest_snapshot"], "total_downloads"].sum() == 13
    assert history["total_downloads"].sum() == 53


def test_cutoff_excludes_later_snapshots(tmp_path):
    write_snapshot(tmp_path, "2026-07-01", [(1, 2023, 6, 30, 10), (1, 2026, 6, 4, 0)])
    write_snapshot(tmp_path, "2026-08-01", [(1, 2026, 6, 5, 0), (1, 2026, 7, 3, 0)])
    history = bh.build_history(tmp_path, cutoff="2026-07-01")

    assert len(history) == 2  # July 2026 exists only in the later snapshot
    assert set(history["source_snapshot"]) == {"2026-07-01"}
    assert get_row(history, 1, 2026, 6)["total_downloads"] == 4
    assert history["in_latest_snapshot"].all()

    # Rows a saved history took from later snapshots respect the cutoff too.
    save_history(tmp_path)
    pd.testing.assert_frame_equal(bh.build_history(tmp_path, cutoff="2026-07-01"), history)


def test_latest_and_other_undated_files_are_ignored(tmp_path):
    write_snapshot(tmp_path, "2026-08-01", [(1, 2026, 7, 5, 5)])
    write_snapshot(tmp_path, "2026-08-01", [(1, 2026, 7, 99, 99), (2, 2026, 7, 1, 1)],
                   name="nanda_usage_timeseries_latest.csv")
    write_snapshot(tmp_path, "2026-08-01", [(3, 2026, 7, 1, 1)],
                   name="nanda_usage_timeseries_2026-08-01_revised.csv")
    history = bh.build_history(tmp_path)

    assert list(history["study_id"]) == [1]
    assert get_row(history, 1, 2026, 7)["total_downloads"] == 10


def test_saved_history_keeps_row_whose_dated_file_is_gone(tmp_path):
    older = write_snapshot(tmp_path, "2026-07-01", [(1, 2023, 6, 30, 10), (1, 2023, 7, 5, 5)])
    write_snapshot(tmp_path, "2026-08-01", [(1, 2023, 7, 6, 5)])
    save_history(tmp_path)
    older.unlink()
    history = bh.build_history(tmp_path)

    june = get_row(history, 1, 2023, 6)
    assert june["total_downloads"] == 40
    assert june["source_snapshot"] == "2026-07-01"
    assert not june["in_latest_snapshot"]
    assert get_row(history, 1, 2023, 7)["total_downloads"] == 11


def test_rerun_on_same_date_prefers_dated_file_over_saved_history(tmp_path):
    snapshot = write_snapshot(tmp_path, "2026-08-01", [(1, 2026, 7, 5, 5)])
    save_history(tmp_path)
    snapshot.unlink()
    write_snapshot(tmp_path, "2026-08-01", [(1, 2026, 7, 6, 6)])  # scraper re-run that day

    assert get_row(bh.build_history(tmp_path), 1, 2026, 7)["total_downloads"] == 12


def test_unreadable_saved_history_is_skipped_with_warning(tmp_path, capsys):
    write_snapshot(tmp_path, "2026-08-01", [(1, 2026, 7, 5, 5)])
    (tmp_path / bh.HISTORY_CSV_NAME).write_text(
        ",".join(bh.HISTORY_COLUMNS) + "\n"
        "<<<<<<< HEAD\n"
        "1,2026,6,1,1,2,2026-07-01,False\n"
        "=======\n"
        "1,2026,6,2,2,4,2026-07-01,False\n"
        ">>>>>>> upstream\n",
        encoding="utf-8",
    )
    history = bh.build_history(tmp_path)

    assert get_row(history, 1, 2026, 7)["total_downloads"] == 10
    assert len(history) == 1
    assert "::warning" in capsys.readouterr().out


def test_empty_or_missing_data_dir_does_not_crash(tmp_path):
    for data_dir in (tmp_path / "missing", tmp_path):
        history = bh.build_history(data_dir)
        assert history.empty
        assert list(history.columns) == bh.HISTORY_COLUMNS

    # A header-only snapshot (every curated request failed) is empty too,
    # and the downstream helpers cope with an empty history.
    write_snapshot(tmp_path, "2026-08-01", [])
    history = bh.build_history(tmp_path)
    assert history.empty
    stats = pd.DataFrame({"study_id": [1], "total_downloads": [7]})
    assert list(bh.apply_history_totals(stats, history)["total_downloads"]) == [7]
    assert bh.preserved_downloads(history) == 0


# ---------------------------------------------------------------------------
# Helpers used by the dashboard and the delta report
# ---------------------------------------------------------------------------

def test_apply_history_totals_replaces_only_studies_with_history(tmp_path):
    write_snapshot(tmp_path, "2026-07-01", [(1, 2023, 6, 30, 10), (1, 2023, 7, 5, 5)])
    write_snapshot(tmp_path, "2026-08-01", [(1, 2023, 7, 6, 5), (2, 2026, 7, 3, 0)])
    history = bh.build_history(tmp_path)
    stats = pd.DataFrame({"study_id": [1, 2, 3],
                          "total_downloads": [11, 3, 500],
                          "unique_users": [4.0, 1.0, None]})
    out = bh.apply_history_totals(stats, history)

    assert list(out["total_downloads"]) == [51, 3, 500]
    assert list(stats["total_downloads"]) == [11, 3, 500]  # input untouched
    pd.testing.assert_series_equal(out["unique_users"], stats["unique_users"])


def test_preserved_downloads_is_measured_per_study(tmp_path):
    # Study 1 lost June 2023 in a trim. Study 2's time-series request failed
    # in August, so its rows all come from July; none of them were dropped.
    write_snapshot(tmp_path, "2026-07-01", [(1, 2023, 6, 30, 10), (1, 2023, 7, 5, 5),
                                            (2, 2026, 6, 8, 0)])
    write_snapshot(tmp_path, "2026-08-01", [(1, 2023, 7, 6, 5)])
    history = bh.build_history(tmp_path)

    assert not get_row(history, 2, 2026, 6)["in_latest_snapshot"]
    assert bh.preserved_downloads(history) == 40
    assert bh.preserved_downloads(history, study_ids=[2]) == 0


def test_main_writes_history_that_reads_back_identically(tmp_path, monkeypatch, capsys):
    write_snapshot(tmp_path, "2026-07-01", [(1, 2023, 6, 30, 10), (1, 2026, 6, 2, 0),
                                            (2, 2026, 6, 8, 0)])
    write_snapshot(tmp_path, "2026-08-01", [(1, 2026, 6, 2, 0), (2, 2026, 6, 8, 0),
                                            (2, 2026, 7, 1, 2)])
    monkeypatch.setattr(bh, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bh, "HISTORY_CSV", tmp_path / bh.HISTORY_CSV_NAME)
    bh.main()

    assert ("4 rows, 2 studies, 2023-06 to 2026-07, 40 downloads preserved"
            in capsys.readouterr().out)
    saved = bh.read_history(tmp_path / bh.HISTORY_CSV_NAME)
    pd.testing.assert_frame_equal(saved, bh.build_history(tmp_path))
