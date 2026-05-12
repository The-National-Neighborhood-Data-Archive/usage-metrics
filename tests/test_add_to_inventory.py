"""Tests for add_to_inventory.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import add_to_inventory as ati  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Study IDs reserved for tests — never appear in the real inventory.csv.
TEST_NEW_IDS = {999900, 999001, 888777}
# A study that DOES exist in the real inventory; we copy that row into the
# fixture to exercise duplicate-handling code.
EXISTING_ID = 38506


@pytest.fixture
def temp_inventory(tmp_path, monkeypatch):
    """Copy of inventory.csv in a temp dir, stripped of any test IDs."""
    src = REPO_ROOT / "inventory.csv"
    df = pd.read_csv(src, dtype={"study_id": int})
    df = df[~df["study_id"].isin(TEST_NEW_IDS)].reset_index(drop=True)
    dst = tmp_path / "inventory.csv"
    df.to_csv(dst, index=False)
    monkeypatch.setattr(ati, "INVENTORY_PATH", dst)
    return dst


def make_datacite_attrs(title: str, version: str = "v1",
                       created: str = "2026-05-12T18:27:39.000Z") -> dict:
    return {
        "titles": [{"title": title}],
        "version": version,
        "created": created,
    }


PARKS_ATTRS = make_datacite_attrs(
    "National Neighborhood Data Archive (NaNDA): Parks and Proximity to "
    "Polluting Sites by Census Tract and ZIP Code Tabulation Area (ZCTA), "
    "United States, 2024",
)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_happy_path_icpsr_appends_row(temp_inventory):
    before = pd.read_csv(temp_inventory)
    args = ati.parse_args(["999900", "--archive", "ICPSR"])
    parks_for_test = make_datacite_attrs(
        PARKS_ATTRS["titles"][0]["title"],
        version="V1",
    )
    with patch.object(ati, "fetch_datacite", return_value=parks_for_test):
        rc = ati.run(args)
    assert rc == 0
    after = pd.read_csv(temp_inventory)
    assert len(after) == len(before) + 1
    new_row = after.iloc[-1]
    assert new_row["study_id"] == 999900
    assert new_row["archive"] == "ICPSR"
    assert new_row["deposit_via"] == "legacy"
    assert new_row["status"] == "published"
    assert new_row["title"].startswith(ati.TITLE_PREFIX)
    assert new_row["version"] == "V1"
    assert new_row["version_date"] == "5/12/2026"
    assert new_row["doi"] == "10.3886/ICPSR999900.v1"
    assert new_row["url"].startswith("https://www.icpsr.umich.edu/")


def test_happy_path_openicpsr_appends_row(temp_inventory):
    before = pd.read_csv(temp_inventory)
    attrs = make_datacite_attrs(
        "National Neighborhood Data Archive (NaNDA): Test Dataset, United States, 2026",
        version="V1.0",
        created="2026-03-15T10:00:00.000Z",
    )
    args = ati.parse_args(["999001", "--archive", "openICPSR"])
    # First DOI candidate (E999001V1) hits; no further DataCite calls expected.
    with patch.object(ati, "fetch_datacite", return_value=attrs) as mock_dc:
        rc = ati.run(args)
    assert rc == 0
    mock_dc.assert_called_once_with("10.3886/E999001V1")
    after = pd.read_csv(temp_inventory)
    assert len(after) == len(before) + 1
    new_row = after.iloc[-1]
    assert new_row["study_id"] == 999001
    assert new_row["archive"] == "openICPSR"
    assert new_row["version"] == "V1.0"
    assert new_row["version_date"] == "3/15/2026"
    assert new_row["doi"] == "10.3886/E999001V1"


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------

def test_duplicate_without_force_errors_and_leaves_csv(temp_inventory):
    # 38506 is already in the inventory.
    before = temp_inventory.read_bytes()
    args = ati.parse_args(["38506", "--archive", "ICPSR"])
    with patch.object(ati, "fetch_datacite", return_value=PARKS_ATTRS):
        rc = ati.run(args)
    assert rc == 2
    assert temp_inventory.read_bytes() == before


def test_duplicate_with_force_replaces_row(temp_inventory):
    before = pd.read_csv(temp_inventory)
    n_before = len(before)
    attrs = make_datacite_attrs(
        "National Neighborhood Data Archive (NaNDA): Voter Registration, "
        "Turnout, and Partisanship by County, United States, 2004-2024",
        version="V3",
        created="2026-05-12T00:00:00.000Z",
    )
    args = ati.parse_args(["38506", "--archive", "ICPSR", "--force"])
    with patch.object(ati, "fetch_datacite", return_value=attrs):
        rc = ati.run(args)
    assert rc == 0
    after = pd.read_csv(temp_inventory)
    assert len(after) == n_before
    row = after.loc[after["study_id"] == 38506].iloc[0]
    assert row["version"] == "V3"
    assert row["version_date"] == "5/12/2026"


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def test_dry_run_does_not_modify_csv(temp_inventory):
    before = temp_inventory.read_bytes()
    args = ati.parse_args(["999900", "--archive", "ICPSR", "--dry-run"])
    with patch.object(ati, "fetch_datacite", return_value=PARKS_ATTRS):
        rc = ati.run(args)
    assert rc == 0
    assert temp_inventory.read_bytes() == before


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_validation_failure_bad_title(temp_inventory):
    before = temp_inventory.read_bytes()
    bad = make_datacite_attrs("Some other dataset that is not NaNDA")
    args = ati.parse_args(["999900", "--archive", "ICPSR"])
    with patch.object(ati, "fetch_datacite", return_value=bad):
        rc = ati.run(args)
    assert rc == 4
    assert temp_inventory.read_bytes() == before


def test_validation_failure_bad_version(temp_inventory):
    before = temp_inventory.read_bytes()
    bad = make_datacite_attrs(
        "National Neighborhood Data Archive (NaNDA): Something",
        version="draft",
    )
    args = ati.parse_args(["999900", "--archive", "ICPSR"])
    with patch.object(ati, "fetch_datacite", return_value=bad):
        rc = ati.run(args)
    assert rc == 4
    assert temp_inventory.read_bytes() == before


# ---------------------------------------------------------------------------
# HTTP failures
# ---------------------------------------------------------------------------

def test_http_failure_exits_non_zero_and_leaves_csv(temp_inventory):
    before = temp_inventory.read_bytes()
    args = ati.parse_args(["999900", "--archive", "ICPSR"])

    def boom(_doi):
        raise requests.ConnectionError("network down")

    with patch.object(ati, "fetch_datacite", side_effect=boom), \
         patch.object(ati, "fetch_json_ld", side_effect=requests.ConnectionError("page down")):
        rc = ati.run(args)
    assert rc == 3
    assert temp_inventory.read_bytes() == before


def test_falls_back_to_json_ld_when_datacite_404(temp_inventory):
    before = pd.read_csv(temp_inventory)
    title = ("National Neighborhood Data Archive (NaNDA): Some new dataset, "
             "United States, 2026")
    ld = {
        "name": title,
        "version": "V1",
        "dateModified": "2026-05-12",
        "identifier": {"value": "doi:10.3886/ICPSR888777.v1"},
    }
    args = ati.parse_args(["888777", "--archive", "ICPSR"])
    with patch.object(ati, "fetch_datacite", return_value=None), \
         patch.object(ati, "fetch_json_ld", return_value=ld):
        rc = ati.run(args)
    assert rc == 0
    after = pd.read_csv(temp_inventory)
    assert len(after) == len(before) + 1
    new_row = after.iloc[-1]
    assert new_row["doi"] == "10.3886/ICPSR888777.v1"
    assert new_row["version"] == "V1"
    assert new_row["version_date"] == "5/12/2026"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_iso_to_slash_date():
    assert ati.iso_to_slash_date("2024-10-14") == "10/14/2024"
    assert ati.iso_to_slash_date("2026-05-12T18:27:39.000Z") == "5/12/2026"
    assert ati.iso_to_slash_date("") == ""


def test_validate_row_accepts_clean_row():
    row = {
        "study_id": 305511, "archive": "ICPSR", "deposit_via": "legacy",
        "status": "published",
        "title": "National Neighborhood Data Archive (NaNDA): Foo",
        "version": "V1", "version_date": "5/12/2026",
        "doi": "10.3886/ICPSR305511.v1",
        "url": "https://www.icpsr.umich.edu/sites/icpsr/view/studies/305511",
    }
    assert ati.validate_row(row) == []
