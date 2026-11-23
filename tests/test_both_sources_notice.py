"""Tests for the one-time two-source notice shared by generate_delta.py and build_dashboard.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import generate_delta as gd  # noqa: E402

INVENTORY = pd.DataFrame({
    "study_id":    [1, 2, 3, 4],
    "archive":     ["openICPSR", "openICPSR", "openICPSR", "ICPSR"],
    "deposit_via": ["legacy", "legacy", "RDE", "legacy"],
})

# First two-source snapshot: 1 and 2 were read from the old source before,
# 3 from the new source. Newly counted = current deposit for 1 and 2 (178 + 0),
# earlier version for 3 (4).
CURRENT = pd.DataFrame({
    "study_id": [1, 2, 3, 4],
    "total_downloads": [576, 27, 35, 5000],
    "earlier_version_downloads": [398, 27, 4, None],
    "current_deposit_downloads": [178, 0, 31, None],
})
OLD_PREVIOUS = pd.DataFrame({"study_id": [1, 2, 3, 4], "total_downloads": [398, 27, 31, 4900]})


def test_notice_on_first_two_source_snapshot():
    assert gd.newly_counted_downloads(CURRENT, OLD_PREVIOUS, INVENTORY) == (182, 2)
    text = gd.first_both_sources_notice(CURRENT, OLD_PREVIOUS, INVENTORY)
    assert text == ("This month's totals include downloads from ICPSR's self-deposit system for the "
                    "first time (182 downloads across 2 datasets). Earlier months did not count them.")


def test_no_notice_when_previous_already_has_the_columns():
    assert gd.first_both_sources_notice(CURRENT, CURRENT, INVENTORY) is None


def test_no_notice_when_current_lacks_or_only_pads_the_columns():
    old = CURRENT[["study_id", "total_downloads"]]
    assert gd.first_both_sources_notice(old, OLD_PREVIOUS, INVENTORY) is None
    padded = old.assign(earlier_version_downloads=pd.NA, current_deposit_downloads=pd.NA)
    assert gd.first_both_sources_notice(padded, OLD_PREVIOUS, INVENTORY) is None


def test_no_notice_without_previous_or_inventory():
    assert gd.first_both_sources_notice(CURRENT, None, INVENTORY) is None
    assert gd.first_both_sources_notice(CURRENT, OLD_PREVIOUS, None) is None


def test_current_with_archive_already_merged_is_fine():
    merged = CURRENT.merge(INVENTORY[["study_id", "archive"]], on="study_id")
    assert gd.newly_counted_downloads(merged, OLD_PREVIOUS, INVENTORY) == (182, 2)
