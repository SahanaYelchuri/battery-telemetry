"""Checks that run on one discharge session.

Each check returns a CheckResult so the report and the tests can use the same logic.
"""

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CheckResult:
    name: str
    passed: bool
    summary: str
    details: dict = field(default_factory=dict)


def percent_never_rises(session):
    """On battery, the reported % should never go up."""
    rises = session["percent"].diff() > 0
    count = int(rises.sum())
    return CheckResult(
        "percent never rises on battery",
        count == 0,
        "no increases" if count == 0 else f"{count} increase(s) while unplugged",
        {"rise_times": session.loc[rises, "timestamp"].tolist()},
    )


def percent_steps_are_small(session, max_step=2):
    """The % should drop smoothly, not jump several points at once."""
    drops = -session["percent"].diff()
    worst = float(drops.max()) if len(drops.dropna()) else 0.0
    return CheckResult(
        f"percent drops at most {max_step} per sample",
        worst <= max_step,
        f"largest single drop: {worst:g}%",
        {"largest_drop": worst},
    )


def percent_matches_capacity(session, tolerance=2.0):
    """The % shown should match remaining / full-charge capacity."""
    calc = 100 * session["remaining_mwh"] / session["full_charge_mwh"]
    diff = (session["percent"] - calc).abs().dropna()
    worst = float(diff.max()) if len(diff) else 0.0
    return CheckResult(
        f"percent within {tolerance}% of remaining/full capacity",
        worst <= tolerance,
        f"largest mismatch: {worst:.2f}%",
        {"largest_mismatch": worst},
    )


def charge_not_stuck(session, max_minutes=10):
    """Remaining charge should keep dropping while the battery is powering the laptop.

    Flags stretches where remaining_mwh stays frozen for longer than max_minutes
    even though the battery reports it is discharging.
    """
    s = session[session["discharge_rate_mw"] > 0]
    if s.empty:
        return CheckResult(f"charge reading never frozen > {max_minutes} min", True, "no discharge data")
    run_id = s["remaining_mwh"].ne(s["remaining_mwh"].shift()).cumsum()
    worst, worst_info = 0.0, {}
    for _, run in s.groupby(run_id):
        minutes = (run["timestamp"].iloc[-1] - run["timestamp"].iloc[0]).total_seconds() / 60
        if minutes > worst:
            # energy actually used during the frozen stretch, from the measured power draw
            used_mwh = run["discharge_rate_mw"].mean() * minutes / 60
            worst = minutes
            worst_info = {
                "start": run["timestamp"].iloc[0], "end": run["timestamp"].iloc[-1],
                "percent": int(run["percent"].iloc[0]), "frozen_at_mwh": int(run["remaining_mwh"].iloc[0]),
                "energy_used_mwh": round(used_mwh),
            }
    summary = f"longest frozen reading: {worst:.0f} min"
    if worst > max_minutes:
        summary += (f" at {worst_info['percent']}% ({worst_info['frozen_at_mwh']} mWh) while about "
                    f"{worst_info['energy_used_mwh']} mWh was actually used")
    return CheckResult(f"charge reading never frozen > {max_minutes} min", worst <= max_minutes,
                       summary, {"longest_minutes": worst, **worst_info})


def estimate_accuracy(session, checkpoints=(90, 75, 50, 25, 10), max_error=0.25, empty_at=5):
    """Compare Windows' 'time remaining' estimate to how long the battery really lasted.

    "Actually lasted" = time from that sample to the end of the session.
    That is only a fair comparison if the session ended because the battery ran out,
    so runs that were stopped early (above empty_at %) are skipped.
    """
    last_pct = session["percent"].iloc[-1]
    if last_pct > empty_at:
        return CheckResult("time-remaining estimate accuracy", True,
                           f"skipped: run stopped at {last_pct:g}%, not near empty", {"table": pd.DataFrame()})
    end = session["timestamp"].iloc[-1]
    rows = []
    for pct in checkpoints:
        hit = session[(session["percent"] <= pct) & session["os_secs_left"].notna()]
        if hit.empty:
            continue
        r = hit.iloc[0]
        est_min = r["os_secs_left"] / 60
        actual_min = (end - r["timestamp"]).total_seconds() / 60
        if actual_min <= 0:
            continue
        rows.append({
            "percent": int(r["percent"]),
            "estimate_min": round(est_min),
            "actual_min": round(actual_min),
            "error_pct": round(100 * (est_min - actual_min) / actual_min),
        })
    table = pd.DataFrame(rows)
    if table.empty:
        return CheckResult("time-remaining estimate accuracy", True, "no estimates to compare", {"table": table})
    worst = int(table["error_pct"].abs().max())
    return CheckResult(
        f"time-remaining estimate within {int(max_error * 100)}% of actual",
        worst <= max_error * 100,
        f"worst error: {worst}% (negative = guessed too short)",
        {"table": table},
    )


def capacity_health(df, design_mwh=None):
    """How much the battery holds now vs when new, and whether the gauge recalibrated."""
    full = df["full_charge_mwh"].dropna()
    design = design_mwh or (df["design_mwh"].dropna().iloc[0] if df["design_mwh"].notna().any() else None)
    changes = df.loc[df["full_charge_mwh"].ne(df["full_charge_mwh"].shift()) & df.index.to_series().gt(0),
                     ["timestamp", "percent", "full_charge_mwh"]]
    latest = int(full.iloc[-1]) if len(full) else None
    health = round(100 * latest / design, 1) if (latest and design) else None
    summary = f"full charge now {latest} mWh"
    if health is not None:
        summary += f" = {health}% of design ({int(design)} mWh)"
    if len(changes):
        summary += f"; gauge recalibrated {len(changes)} time(s)"
    return CheckResult("battery capacity", True, summary,
                       {"latest_full_mwh": latest, "design_mwh": design, "health_pct": health,
                        "recalibrations": changes.reset_index(drop=True)})


def load_vs_drain(session):
    """How strongly CPU load tracks power draw (correlation)."""
    s = session[["cpu_percent", "discharge_rate_mw"]].dropna()
    s = s[s["discharge_rate_mw"] > 0]
    corr = float(s["cpu_percent"].corr(s["discharge_rate_mw"])) if len(s) > 2 else float("nan")
    return CheckResult("CPU load vs power draw", True,
                       f"median draw {s['discharge_rate_mw'].median() / 1000:.1f} W, "
                       f"correlation with CPU load {corr:.2f}",
                       {"correlation": corr, "median_mw": float(s["discharge_rate_mw"].median())})


def charge_profile(session):
    """Summarize a charging session: how fast it charged and when it slowed down near full."""
    s = session[session["charge_rate_mw"] > 0]
    if s.empty:
        return CheckResult("charging profile", True, "no charging data", {})

    def time_to(pct):
        hit = session[session["percent"] >= pct]
        return hit["timestamp"].iloc[0] if len(hit) else None

    start = session["timestamp"].iloc[0]
    full_at, done_at = time_to(100), s["timestamp"].iloc[-1]

    # charging power at a few battery levels shows where it slows down near full
    watts_at = {}
    for pct in (20, 50, 80, 90, 95):
        hit = s[s["percent"] >= pct]
        if len(hit) and session["percent"].iloc[0] < pct:
            watts_at[pct] = round(hit["charge_rate_mw"].iloc[0] / 1000, 1)

    details = {
        "start_percent": int(session["percent"].iloc[0]),
        "peak_watts": round(s["charge_rate_mw"].max() / 1000, 1),
        "watts_at_percent": watts_at,
        "minutes_to_100_shown": round((full_at - start).total_seconds() / 60) if full_at is not None else None,
        "minutes_charging_after_100_shown": (round((done_at - full_at).total_seconds() / 60)
                                             if full_at is not None and done_at > full_at else 0),
    }
    summary = (f"{details['start_percent']}% -> 100% shown in {details['minutes_to_100_shown']} min, "
               f"peak {details['peak_watts']} W; power at "
               + ", ".join(f"{p}%: {w} W" for p, w in watts_at.items()))
    if details["minutes_charging_after_100_shown"]:
        summary += f"; kept charging {details['minutes_charging_after_100_shown']} min after showing 100%"
    return CheckResult("charging profile", True, summary, details)


DISCHARGE_CHECKS = [percent_never_rises, percent_steps_are_small, percent_matches_capacity,
                    charge_not_stuck, estimate_accuracy]
