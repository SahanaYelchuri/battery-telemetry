"""Tests for the charging profile summary."""

from battery_analysis import checks
from conftest import make_log


def charging_log():
    # 50% -> 100%: 30 W until 80%, then slowing down, then 5 more samples still charging at 100%
    percents = list(range(50, 101)) + [100] * 5
    rates = [30000 if p < 80 else 30000 - (p - 79) * 1200 for p in range(50, 101)] + [2000] * 5
    return make_log(percents, plugged=1, rate_mw=0).assign(charge_rate_mw=rates)


def test_charge_profile_reports_power_at_levels():
    r = checks.charge_profile(charging_log())
    assert r.details["peak_watts"] == 30.0
    assert r.details["watts_at_percent"][80] == 28.8
    assert r.details["watts_at_percent"][95] < 15


def test_charge_profile_counts_charging_after_showing_100():
    r = checks.charge_profile(charging_log())
    assert r.details["minutes_charging_after_100_shown"] == 1  # 5 samples x 10 s, rounded


def test_charge_profile_handles_no_charging():
    r = checks.charge_profile(make_log([100, 100], plugged=1, rate_mw=0))
    assert r.summary == "no charging data"
