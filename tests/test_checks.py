"""Each check should pass on good data and fail on the problem it looks for."""

import pytest

from battery_analysis import checks
from conftest import make_log


def test_percent_never_rises_passes_on_clean_data(smooth_discharge):
    assert checks.percent_never_rises(smooth_discharge).passed


def test_percent_never_rises_catches_a_rise():
    assert not checks.percent_never_rises(make_log([80, 79, 81, 78])).passed


def test_small_steps_pass(smooth_discharge):
    assert checks.percent_steps_are_small(smooth_discharge).passed


def test_big_jump_fails():
    result = checks.percent_steps_are_small(make_log([60, 59, 50]), max_step=2)
    assert not result.passed
    assert result.details["largest_drop"] == 9


def test_percent_matches_capacity_passes(smooth_discharge):
    assert checks.percent_matches_capacity(smooth_discharge).passed


def test_percent_mismatch_fails():
    df = make_log([50, 49])
    df.loc[1, "remaining_mwh"] = 0.40 * 40000  # gauge says 40% but screen says 49%
    assert not checks.percent_matches_capacity(df).passed


def test_charge_not_stuck_passes(smooth_discharge):
    assert checks.charge_not_stuck(smooth_discharge).passed


def test_frozen_charge_reading_fails():
    # 7% held for 30 minutes (180 samples at 10s) while still drawing 5 W
    df = make_log([8] + [7] * 180 + [6])
    df["remaining_mwh"] = [3200] + [2800] * 180 + [2400]
    result = checks.charge_not_stuck(df, max_minutes=10)
    assert not result.passed
    assert result.details["percent"] == 7
    # 5 W for 179 sample gaps x 10 s = 29.8 min -> about 2486 mWh
    assert result.details["energy_used_mwh"] == pytest.approx(2486, abs=5)


def test_accurate_estimate_passes():
    n = 100
    # 100% down to 1%; every sample's estimate equals the true time left
    df = make_log(list(range(100, 100 - n, -1)), secs_left=[10 * (n - 1 - i) for i in range(n)])
    df.loc[n - 1, "os_secs_left"] = float("nan")
    assert checks.estimate_accuracy(df, checkpoints=(90, 75, 50)).passed


def test_bad_estimate_fails():
    n = 100
    df = make_log(list(range(100, 100 - n, -1)), secs_left=[60] * n)  # always says 1 min left
    result = checks.estimate_accuracy(df, checkpoints=(90, 75, 50))
    assert not result.passed
    assert (result.details["table"]["error_pct"] < 0).all()  # guessed too short


def test_estimate_skipped_when_run_stopped_early():
    # stopped at 40%: we don't know how long it would really have lasted, so don't judge
    df = make_log(list(range(100, 39, -1)), secs_left=[60] * 61)
    result = checks.estimate_accuracy(df, checkpoints=(90, 75, 50))
    assert result.passed
    assert result.summary.startswith("skipped")


def test_capacity_health_uses_design_capacity():
    df = make_log([90, 89], full_mwh=[40000, 38000])
    result = checks.capacity_health(df, design_mwh=50000)
    assert result.details["health_pct"] == 76.0
    assert len(result.details["recalibrations"]) == 1


def test_load_vs_drain_finds_positive_correlation():
    df = make_log([90, 89, 88, 87], cpu=[5, 20, 50, 90], rate_mw=[4000, 6000, 12000, 20000])
    assert checks.load_vs_drain(df).details["correlation"] > 0.9
