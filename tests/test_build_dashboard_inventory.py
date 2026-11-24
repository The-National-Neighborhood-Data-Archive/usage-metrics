"""The dashboard takes title, version, doi, and url from inventory.csv at build time."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import build_dashboard as bd  # noqa: E402

SNAPSHOT = pd.DataFrame({
    "study_id": [1, 2, 3],
    "dataset_title": ["Old title one", "Old title two", "Only in snapshot"],
    "doi": ["10.3886/ICPSR1", "10.3886/E2", "10.3886/ICPSR3"],
    "url": ["https://old/1", "https://old/2", "https://old/3"],
    "total_downloads": [10, 20, 30],
})

INVENTORY = pd.DataFrame({
    "study_id": [1, 2],
    "archive": ["ICPSR", "openICPSR"],
    "deposit_via": ["legacy", "RDE"],
    "status": ["published", "unpublished"],
    "title": ["National Neighborhood Data Archive (NaNDA): New title one", "New title two"],
    "version": ["V2", "V1.3"],
    "version_date": ["1/1/2026", "2/2/2026"],
    "doi": ["10.3886/ICPSR1.v2", "10.3886/E2V13"],
    "url": ["https://new/1", "https://new/2"],
})


def test_inventory_values_replace_snapshot_values():
    out = bd.apply_inventory_details(SNAPSHOT, INVENTORY).set_index("study_id")
    assert out.loc[1, "dataset_title"] == "New title one"      # NaNDA prefix stripped
    assert out.loc[1, "doi"] == "10.3886/ICPSR1.v2"
    assert out.loc[1, "url"] == "https://new/1"
    assert out.loc[1, "version"] == "V2"
    assert out.loc[2, "dataset_title"] == "New title two"
    assert out.loc[2, "version"] == "V1.3"
    assert (out.loc[1, "archive"], out.loc[1, "pub_status"]) == ("ICPSR", "published")
    assert (out.loc[2, "archive"], out.loc[2, "pub_status"]) == ("openICPSR", "unpublished")


def test_snapshot_values_kept_for_a_study_missing_from_inventory():
    out = bd.apply_inventory_details(SNAPSHOT, INVENTORY).set_index("study_id")
    assert out.loc[3, "dataset_title"] == "Only in snapshot"
    assert out.loc[3, "doi"] == "10.3886/ICPSR3"
    assert out.loc[3, "url"] == "https://old/3"
    assert pd.isna(out.loc[3, "version"]) or out.loc[3, "version"] == ""
    assert pd.isna(out.loc[3, "archive"])


def test_blank_inventory_cell_does_not_erase_snapshot_value():
    inv = INVENTORY.copy()
    inv.loc[0, "url"] = None
    out = bd.apply_inventory_details(SNAPSHOT, inv).set_index("study_id")
    assert out.loc[1, "url"] == "https://old/1"


def test_no_inventory_file():
    out = bd.apply_inventory_details(SNAPSHOT, None)
    assert list(out["dataset_title"]) == list(SNAPSHOT["dataset_title"])
    assert (out["archive"] == "ICPSR").all() and (out["pub_status"] == "published").all()
    assert "version" in out.columns


def test_duplicate_inventory_id_does_not_duplicate_rows(capsys):
    inv = pd.concat([INVENTORY, INVENTORY.iloc[[0]]], ignore_index=True)
    out = bd.apply_inventory_details(SNAPSHOT, inv)
    assert list(out["study_id"]) == [1, 2, 3]
    assert "duplicate" in capsys.readouterr().out.lower()


def test_all_blank_snapshot_column_is_overridden():
    snap = SNAPSHOT.copy()
    snap["url"] = float("nan")          # an all-NaN float column, as pandas reads a blank column
    out = bd.apply_inventory_details(snap, INVENTORY).set_index("study_id")
    assert out.loc[1, "url"] == "https://new/1"
    assert pd.isna(out.loc[3, "url"])


def test_row_order_and_count_unchanged():
    out = bd.apply_inventory_details(SNAPSHOT, INVENTORY)
    assert list(out["study_id"]) == [1, 2, 3]
    assert len(out) == 3
