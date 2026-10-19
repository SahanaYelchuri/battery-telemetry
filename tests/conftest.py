"""Helpers to build small fake battery logs for tests."""

import pandas as pd
import pytest

from battery_analysis.load import split_sessions


def make_log(percents, step_s=10, full_mwh=40000, plugged=0, start="2026-10-12 00:00:00",
             secs_left=None, rate_mw=5000, cpu=5.0):
    """Build a DataFrame shaped like the logger output from a list of % values."""
    n = len(percents)
    fulls = full_mwh if isinstance(full_mwh, list) else [full_mwh] * n
    times = pd.date_range(start, periods=n, freq=f"{step_s}s")
    df = pd.DataFrame({
        "timestamp": times,
        "elapsed_s": [i * step_s for i in range(n)],
        "label": "test",
        "percent": percents,
        "os_secs_left": secs_left if secs_left is not None else [float("nan")] * n,
        "plugged": plugged if isinstance(plugged, list) else [plugged] * n,
        "cpu_percent": cpu if isinstance(cpu, list) else [cpu] * n,
        "remaining_mwh": [p / 100 * f for p, f in zip(percents, fulls)],
        "full_charge_mwh": fulls,
        "design_mwh": [float("nan")] * n,
        "voltage_mv": [15000] * n,
        "discharge_rate_mw": rate_mw if isinstance(rate_mw, list) else [rate_mw] * n,
        "charge_rate_mw": [0] * n,
    })
    return df


@pytest.fixture
def smooth_discharge():
    """A clean discharge: 100% down to 50%, one point per sample."""
    return split_sessions(make_log(list(range(100, 49, -1))))
