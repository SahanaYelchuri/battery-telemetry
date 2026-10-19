"""Validate every real log in data/.

These tests check that the logs themselves are trustworthy (right columns,
sane values, smooth % on battery). Findings about the battery's behavior, like
an inaccurate time estimate, belong in the report, not here.
"""

import glob
import os

import pytest

from battery_analysis import checks
from battery_analysis.load import load_log, sessions, split_sessions

ROOT = os.path.dirname(os.path.dirname(__file__))
LOGS = sorted(glob.glob(os.path.join(ROOT, "data", "**", "*.csv"), recursive=True))
EXPECTED_COLUMNS = {"timestamp", "percent", "plugged", "remaining_mwh", "full_charge_mwh", "voltage_mv"}


def discharge_sessions(path):
    df = split_sessions(load_log(path))
    return list(sessions(df, "discharging", min_rows=30))


@pytest.mark.parametrize("path", LOGS, ids=os.path.basename)
def test_log_has_expected_columns(path):
    df = load_log(path)
    assert EXPECTED_COLUMNS <= set(df.columns)


@pytest.mark.parametrize("path", LOGS, ids=os.path.basename)
def test_values_are_in_range(path):
    df = load_log(path)
    assert df["percent"].between(0, 100).all()
    assert (df["remaining_mwh"].dropna() <= df["full_charge_mwh"].max() * 1.05).all()
    assert (df["voltage_mv"].dropna() > 0).all()


@pytest.mark.parametrize("path", LOGS, ids=os.path.basename)
def test_battery_percent_behaves_on_battery(path):
    for sid, s in discharge_sessions(path):
        for check in (checks.percent_never_rises, checks.percent_steps_are_small,
                      checks.percent_matches_capacity):
            result = check(s)
            assert result.passed, f"session {sid}: {result.name}: {result.summary}"
