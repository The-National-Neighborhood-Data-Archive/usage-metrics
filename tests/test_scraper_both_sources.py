"""Offline tests for nanda_usage_scraper's two-source handling of openICPSR rows."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import nanda_usage_scraper as sc  # noqa: E402

# Reserved test IDs (see CLAUDE.md): never in the real inventory.
PUB, UNPUB, CURATED = 999900, 999001, 888777

INVENTORY = {
    PUB:     {"archive": "openICPSR", "deposit_via": "legacy", "status": "published",
              "title": "Pub", "doi": "10.3886/E999900V1", "url": "u"},
    UNPUB:   {"archive": "openICPSR", "deposit_via": "legacy", "status": "unpublished",
              "title": "Unpub", "doi": "10.3886/E999001V1", "url": "u"},
    CURATED: {"archive": "ICPSR", "deposit_via": "legacy", "status": "published",
              "title": "Cur", "doi": "10.3886/ICPSR888777.v1", "url": "u"},
}


class FakeResponse:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else ("" if payload is None else "x")
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        raise RuntimeError(f"HTTP {self.status_code}")


class FakeScraper:
    """Answers by URL substring. `responses`: {"openicpsr": ..., "usage-statistics": ...};
    a value may be a FakeResponse or an Exception to raise."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for key, resp in self.responses.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected url {url}")


def old_source(downloads, views=5):
    return FakeResponse(200, {"totalDownloads": downloads, "totalViews": views})


def new_source(downloads, data=None, docs=0):
    return FakeResponse(200, {"downloadDetails": {
        "totalDownloads": downloads,
        "dataDownloads": downloads if data is None else data,
        "documentationDownloads": docs}})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)


def test_published_row_adds_both_sources():
    s = FakeScraper({"openicpsr": old_source(398, views=2259), "usage-statistics": new_source(178, 170, 8)})
    row = sc.scrape_study(PUB, s, INVENTORY)
    assert row["earlier_version_downloads"] == 398
    assert row["current_deposit_downloads"] == 178
    assert row["total_downloads"] == 576
    assert row["total_views"] == 2259
    assert (row["data_downloads"], row["documentation_downloads"]) == (170, 8)
    assert row["scrape_status"] == "success" and row["error_message"] == ""


def test_rde_openicpsr_row_also_asks_both_sources():
    inv = {PUB: {**INVENTORY[PUB], "deposit_via": "RDE"}}
    s = FakeScraper({"openicpsr": old_source(0), "usage-statistics": new_source(31)})
    row = sc.scrape_study(PUB, s, inv)
    assert len(s.calls) == 2
    assert (row["earlier_version_downloads"], row["current_deposit_downloads"], row["total_downloads"]) == (0, 31, 31)


def test_new_source_failure_keeps_prior_value_and_never_lowers_total():
    prior = {PUB: {"earlier_version_downloads": 398, "current_deposit_downloads": 178,
                   "total_views": 2259, "data_downloads": 170, "documentation_downloads": 8}}
    s = FakeScraper({"openicpsr": old_source(400), "usage-statistics": ConnectionError("unreachable")})
    row = sc.scrape_study(PUB, s, INVENTORY, prior)
    assert row["current_deposit_downloads"] == 178
    assert row["total_downloads"] == 578
    assert "nanda-usage-stats" in row["error_message"]
    assert "kept prior current_deposit_downloads=178" in row["error_message"]
    assert row["scrape_status"] == "success"


def test_old_source_failure_keeps_prior_value():
    prior = {PUB: {"earlier_version_downloads": 398, "current_deposit_downloads": None,
                   "total_views": 2259, "data_downloads": None, "documentation_downloads": None}}
    s = FakeScraper({"openicpsr": FakeResponse(403, text="blocked"), "usage-statistics": new_source(180)})
    row = sc.scrape_study(PUB, s, INVENTORY, prior)
    assert row["earlier_version_downloads"] == 398
    assert row["total_views"] == 2259
    assert row["total_downloads"] == 578
    assert "kept prior earlier_version_downloads=398" in row["error_message"]


def test_failure_with_no_prior_records_zero_not_crash():
    s = FakeScraper({"openicpsr": old_source(10), "usage-statistics": ConnectionError("x")})
    row = sc.scrape_study(PUB, s, INVENTORY, {})
    assert (row["earlier_version_downloads"], row["current_deposit_downloads"], row["total_downloads"]) == (10, 0, 10)


@pytest.mark.parametrize("miss", [FakeResponse(404, text="not found"), FakeResponse(500, text="err"),
                                  FakeResponse(200, None, text=""), FakeResponse(200, {}, text="{}")])
def test_unpublished_row_miss_on_new_source_is_quiet(miss, capsys):
    s = FakeScraper({"openicpsr": old_source(27), "usage-statistics": miss})
    row = sc.scrape_study(UNPUB, s, INVENTORY)
    assert (row["earlier_version_downloads"], row["current_deposit_downloads"], row["total_downloads"]) == (27, 0, 27)
    assert row["error_message"] == ""
    assert "WARN" not in capsys.readouterr().out
    assert len(s.calls) == 2    # no retries on an expected miss


def test_published_row_miss_on_new_source_warns_and_carries_forward(capsys):
    prior = {PUB: {"earlier_version_downloads": 1, "current_deposit_downloads": 50,
                   "total_views": 1, "data_downloads": 50, "documentation_downloads": 0}}
    s = FakeScraper({"openicpsr": old_source(1), "usage-statistics": FakeResponse(404, text="nf")})
    row = sc.scrape_study(PUB, s, INVENTORY, prior)
    assert row["current_deposit_downloads"] == 50 and row["total_downloads"] == 51
    assert "WARN" in capsys.readouterr().out
    assert row["error_message"]


def test_curated_rows_leave_source_columns_blank(monkeypatch):
    monkeypatch.setattr(sc, "fetch_pcms", lambda sid, s: {
        "data_downloads": 7, "documentation_downloads": 3, "total_downloads": 10,
        "unique_users": 4, "num_institutions": 2, "has_data": True})
    monkeypatch.setattr(sc, "fetch_publications_count", lambda sid, s: 1)
    row = sc.scrape_study(CURATED, FakeScraper({}), INVENTORY)
    assert row["total_downloads"] == 10
    assert row["earlier_version_downloads"] is None
    assert row["current_deposit_downloads"] is None


def test_curated_rde_row_still_uses_new_source_only():
    inv = {CURATED: {**INVENTORY[CURATED], "deposit_via": "RDE"}}
    s = FakeScraper({"usage-statistics": new_source(105)})
    row = sc.scrape_study(CURATED, s, inv)
    assert row["total_downloads"] == 105 and len(s.calls) == 1
    assert row["earlier_version_downloads"] is None


def test_csv_columns_include_source_columns_once():
    assert sc.CSV_COLUMNS.index("earlier_version_downloads") < sc.CSV_COLUMNS.index("scrape_status")
    assert sc.CSV_COLUMNS.count("current_deposit_downloads") == 1


def test_load_prior_values_from_old_snapshot_splits_by_route(tmp_path):
    inv = {1: {"archive": "openICPSR", "deposit_via": "legacy"},
           2: {"archive": "openICPSR", "deposit_via": "RDE"},
           3: {"archive": "ICPSR", "deposit_via": "legacy"}}
    path = tmp_path / "nanda_usage_stats_2026-11-02.csv"
    pd.DataFrame({"study_id": [1, 2, 3], "total_downloads": [398, 21, 5000],
                  "total_views": [2259, None, None],
                  "data_downloads": [None, 21, 4000], "documentation_downloads": [None, 0, 1000]}
                 ).to_csv(path, index=False)
    pv = sc.load_prior_values(path, inv)
    assert pv[1]["earlier_version_downloads"] == 398 and pv[1]["current_deposit_downloads"] is None
    assert pv[2]["earlier_version_downloads"] is None and pv[2]["current_deposit_downloads"] == 21
    assert 3 not in pv


def test_load_prior_values_from_new_snapshot_reads_columns(tmp_path):
    inv = {1: {"archive": "openICPSR", "deposit_via": "legacy"}}
    path = tmp_path / "nanda_usage_stats_2026-12-01.csv"
    pd.DataFrame({"study_id": [1], "total_downloads": [576], "total_views": [2300],
                  "data_downloads": [170], "documentation_downloads": [8],
                  "earlier_version_downloads": [398], "current_deposit_downloads": [178]}
                 ).to_csv(path, index=False)
    pv = sc.load_prior_values(path, inv)
    assert (pv[1]["earlier_version_downloads"], pv[1]["current_deposit_downloads"]) == (398, 178)


def test_find_prior_snapshot_ignores_latest_and_same_day(tmp_path):
    for name in ("nanda_usage_stats_latest.csv", "nanda_usage_stats_2026-11-02.csv",
                 "nanda_usage_stats_2026-12-01.csv", "nanda_usage_stats_2026-12-01_revised.csv"):
        (tmp_path / name).write_text("study_id\n")
    assert sc.find_prior_snapshot(tmp_path, before="2026-12-01").name == "nanda_usage_stats_2026-11-02.csv"
    assert sc.find_prior_snapshot(tmp_path).name == "nanda_usage_stats_2026-12-01.csv"
    assert sc.find_prior_snapshot(tmp_path, before="2026-01-01") is None
