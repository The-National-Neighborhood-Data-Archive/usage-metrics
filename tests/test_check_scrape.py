"""Tests for check_scrape.py: the post-scrape guardrail."""

import pandas as pd

import check_scrape as cs

STATS_COLS = ["study_id", "total_downloads", "unique_users"]


def write_stats(path, rows):
    pd.DataFrame(rows, columns=STATS_COLS).to_csv(path, index=False)


def write_ts(path, rows):
    pd.DataFrame(rows, columns=["study_id", "year", "month", "total_downloads"]).to_csv(path, index=False)


def setup(tmp_path, new_rows, ts_rows, prev_rows, date="2026-11-02"):
    new = tmp_path / f"nanda_usage_stats_{date}.csv"
    prev = tmp_path / "nanda_usage_stats_2026-10-01.csv"
    write_stats(new, new_rows)
    write_stats(prev, prev_rows)
    write_ts(tmp_path / f"nanda_usage_timeseries_{date}.csv", ts_rows)
    return new, cs.timeseries_for(new), prev


PREV = [(1, 100, 10), (2, 50, None), (3, 20, None), (4, 0, None)]


def test_healthy_scrape_passes(tmp_path):
    new, ts, prev = setup(tmp_path, [(1, 110, 11), (2, 55, None), (3, 20, None), (4, 0, None)],
                          [(1, 2026, 10, 10)], PREV)
    assert cs.check(new, ts, prev) == []


def test_trim_passes(tmp_path):
    # Totals and users fall, but nothing goes to zero and October is present.
    new, ts, prev = setup(tmp_path, [(1, 80, 7), (2, 50, None), (3, 20, None), (4, 0, None)],
                          [(1, 2026, 10, 3)], PREV)
    assert cs.check(new, ts, prev) == []


def test_empty_scrape_fails_all_three(tmp_path):
    new, ts, prev = setup(tmp_path, [(1, 0, None), (2, 0, None), (3, 0, None), (4, 0, None)],
                          [], PREV)
    assert len(cs.check(new, ts, prev)) == 3


def test_missing_studies_count_as_zeroed(tmp_path):
    new, ts, prev = setup(tmp_path, [(1, 110, 11)], [(1, 2026, 10, 10)], PREV)
    failures = cs.check(new, ts, prev)
    assert failures == ["2 of 3 studies dropped to 0 or went missing"]


def test_january_checks_december(tmp_path):
    new, ts, prev = setup(tmp_path, [(1, 110, 11), (2, 55, None), (3, 20, None)],
                          [(1, 2026, 12, 5)], PREV, date="2027-01-01")
    assert cs.check(new, ts, prev) == []


def test_quarantine_moves_dated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "QUARANTINE_DIR", tmp_path / "quarantine")
    new, ts, _ = setup(tmp_path, [(1, 0, None)], [], PREV)
    dest = cs.quarantine(new)
    assert not new.exists() and not ts.exists()
    assert (dest / new.name).exists() and (dest / ts.name).exists()
    assert dest.name == "2026-11-02"
