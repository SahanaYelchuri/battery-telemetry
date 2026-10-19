"""Tests for loading, cleaning, and splitting logs."""

import math

import pandas as pd

from battery_analysis.load import UNKNOWN_ESTIMATE, gaps, load_log, sessions, split_sessions
from conftest import make_log


def test_unknown_estimate_becomes_blank(tmp_path):
    # Windows reports 4294967295 when it has no time-left estimate
    df = make_log([90, 89], secs_left=[UNKNOWN_ESTIMATE, 3600])
    path = tmp_path / "log.csv"
    df.to_csv(path, index=False)
    clean = load_log(path)
    assert math.isnan(clean["os_secs_left"].iloc[0])
    assert clean["os_secs_left"].iloc[1] == 3600


def test_blank_cells_load_as_nan(tmp_path):
    path = tmp_path / "log.csv"
    make_log([90]).to_csv(path, index=False)
    clean = load_log(path)
    assert clean["design_mwh"].isna().all()


def test_new_session_when_charger_changes():
    df = split_sessions(make_log([50, 49, 49, 50], plugged=[0, 0, 1, 1]))
    assert df["session"].tolist() == [1, 1, 2, 2]
    assert df["state"].tolist() == ["discharging", "discharging", "charging", "charging"]


def test_new_session_after_long_gap():
    df = make_log([50, 49, 48])
    df.loc[2, "timestamp"] += pd.Timedelta(hours=3)  # laptop slept
    df = split_sessions(df)
    assert df["session"].tolist() == [1, 1, 2]


def test_gaps_report_charge_lost_during_sleep():
    df = make_log([50, 40], full_mwh=40000)
    df.loc[1, "timestamp"] = df.loc[0, "timestamp"] + pd.Timedelta(hours=2)
    g = gaps(df)
    assert len(g) == 1
    assert g.loc[0, "hours"] == 2
    assert g.loc[0, "lost_mwh"] == 4000
    assert g.loc[0, "avg_drain_mw"] == 2000


def test_sessions_filters_by_state():
    df = split_sessions(make_log([50, 49, 49, 50], plugged=[0, 0, 1, 1]))
    states = [rows["state"].iloc[0] for _, rows in sessions(df, "charging")]
    assert states == ["charging"]
