"""Tests for generate_delta.py's dashboard-total bullet."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import generate_delta as gd  # noqa: E402

CURRENT = pd.DataFrame({"study_id": [1, 2], "total_downloads": [11, 500]})


def test_dashboard_total_line_omitted_without_history(tmp_path):
    assert gd.dashboard_total_line(CURRENT, tmp_path / "nanda_download_history.csv") is None


def test_dashboard_total_line_reconciles_with_dashboard(tmp_path):
    # Study 1: ICPSR now reports only July 2023 (11); June 2023 (40) was
    # trimmed and survives in the history. Study 2 has no history.
    path = tmp_path / "nanda_download_history.csv"
    pd.DataFrame({
        "study_id": [1, 1], "year": [2023, 2023], "month": [6, 7],
        "data_downloads": [30, 6], "documentation_downloads": [10, 5],
        "total_downloads": [40, 11],
        "source_snapshot": ["2026-07-01", "2026-08-01"],
        "in_latest_snapshot": [False, True],
    }).to_csv(path, index=False)

    assert gd.dashboard_total_line(CURRENT, path) == (
        "- **Dashboard total, including downloads ICPSR no longer reports:** "
        "551 (40 preserved from earlier scrapes)"
    )
