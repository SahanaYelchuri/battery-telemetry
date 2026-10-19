"""Print a findings report for a battery log and save charts.

Usage:
    python -m battery_analysis.report data/personal-idle_2026-10-11.csv
    python -m battery_analysis.report data/work-load.csv --design-mwh 50000 --out reports/work
"""

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from battery_analysis import checks  # noqa: E402
from battery_analysis.load import gaps, load_log, sessions, split_sessions  # noqa: E402

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _style(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED)


def chart_overview(session, path):
    """Battery % and voltage over the session (two panels, one axis each)."""
    hours = (session["timestamp"] - session["timestamp"].iloc[0]).dt.total_seconds() / 3600
    fig, (a, b) = plt.subplots(2, 1, figsize=(8, 5.5), sharex=True)
    a.plot(hours, session["percent"], color=BLUE, linewidth=2)
    _style(a, "Battery level", "%")
    b.plot(hours, session["voltage_mv"] / 1000, color=BLUE, linewidth=2)
    _style(b, "Battery voltage", "volts")
    b.set_xlabel("hours on battery", color=MUTED)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_estimate(session, path):
    """Windows' time-remaining estimate vs how long the battery actually lasted."""
    s = session[session["os_secs_left"].notna()]
    end = session["timestamp"].iloc[-1]
    hours = (s["timestamp"] - session["timestamp"].iloc[0]).dt.total_seconds() / 3600
    actual = (end - s["timestamp"]).dt.total_seconds() / 3600
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(hours, actual, color=BLUE, linewidth=2, label="actual time left")
    ax.plot(hours, s["os_secs_left"] / 3600, color=ORANGE, linewidth=2, label="Windows estimate")
    _style(ax, "Time remaining: Windows estimate vs actual", "hours left")
    ax.set_xlabel("hours on battery", color=MUTED)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_load(session, path):
    """CPU load vs power draw."""
    s = session[session["discharge_rate_mw"] > 0]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(s["cpu_percent"], s["discharge_rate_mw"] / 1000, s=10, color=BLUE, alpha=0.5)
    _style(ax, "Power draw vs CPU load", "watts")
    ax.set_xlabel("CPU load (%)", color=MUTED)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_charging(session, path):
    """Charge rate vs battery %: shows fast charging and the slowdown near full."""
    s = session[session["charge_rate_mw"] > 0]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(s["percent"], s["charge_rate_mw"] / 1000, color=BLUE, linewidth=2)
    _style(ax, "Charging power vs battery level", "watts into battery")
    ax.set_xlabel("battery level (%)", color=MUTED)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run(path, design_mwh=None, out=None, make_charts=True):
    """Analyze one log. Returns a dict of results (used by the tests too)."""
    df = split_sessions(load_log(path))
    name = os.path.splitext(os.path.basename(path))[0]
    out = out or os.path.join("reports", name)
    results = {"capacity": checks.capacity_health(df, design_mwh), "gaps": gaps(df), "sessions": []}

    print(f"\n=== {name} ===")
    print(f"{len(df)} samples, {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    print(f"Capacity: {results['capacity'].summary}")

    if len(results["gaps"]):
        print("\nGaps in logging (sleep / hibernate / logger stopped):")
        print(results["gaps"].to_string(index=False))

    for sid, s in sessions(df, "discharging", min_rows=30):
        hours = (s["timestamp"].iloc[-1] - s["timestamp"].iloc[0]).total_seconds() / 3600
        print(f"\nDischarge session {sid}: {s['percent'].iloc[0]:g}% -> {s['percent'].iloc[-1]:g}% "
              f"in {hours:.1f} h")
        session_results = [f(s) for f in checks.DISCHARGE_CHECKS] + [checks.load_vs_drain(s)]
        for r in session_results:
            print(f"  [{'PASS' if r.passed else 'FAIL'}] {r.name}: {r.summary}")
        estimate = next(r for r in session_results if r.name.startswith("time-remaining"))
        table = estimate.details.get("table")
        if table is not None and len(table):
            print("\n  Estimate vs actual (minutes):")
            print("  " + table.to_string(index=False).replace("\n", "\n  "))
        results["sessions"].append((sid, session_results))

        if make_charts:
            os.makedirs(out, exist_ok=True)
            chart_overview(s, os.path.join(out, f"session{sid}_overview.png"))
            chart_estimate(s, os.path.join(out, f"session{sid}_estimate.png"))
            chart_load(s, os.path.join(out, f"session{sid}_load.png"))
            print(f"  Charts saved to {out}/")

    for sid, s in sessions(df, "charging", min_rows=30):
        r = checks.charge_profile(s)
        print(f"\nCharging session {sid}: {r.summary}")
        results["sessions"].append((sid, [r]))
        if make_charts and r.details:
            os.makedirs(out, exist_ok=True)
            chart_charging(s, os.path.join(out, f"session{sid}_charging.png"))
            print(f"  Chart saved to {out}/")

    return results


def main():
    p = argparse.ArgumentParser(description="Analyze a battery log CSV.")
    p.add_argument("csv", nargs="+", help="one or more logger CSV files")
    p.add_argument("--design-mwh", type=float, help="design capacity from powercfg /batteryreport")
    p.add_argument("--out", help="folder for charts (default: reports/<file name>)")
    p.add_argument("--no-charts", action="store_true")
    args = p.parse_args()
    for path in args.csv:
        run(path, args.design_mwh, args.out, not args.no_charts)


if __name__ == "__main__":
    main()
