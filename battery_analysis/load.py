"""Load and clean battery logs written by battery_logger.py."""

import pandas as pd

# Windows uses 0xFFFFFFFF (4294967295) to mean "no estimate".
UNKNOWN_ESTIMATE = 0xFFFFFFFF

NUMERIC_COLS = [
    "elapsed_s", "percent", "os_secs_left", "plugged", "cpu_percent",
    "remaining_mwh", "full_charge_mwh", "design_mwh",
    "voltage_mv", "discharge_rate_mw", "charge_rate_mw",
]


def load_log(path):
    """Read a logger CSV and return a clean DataFrame sorted by time.

    - timestamps become real datetimes
    - blank cells become NaN
    - the Windows "unknown" estimate becomes NaN
    """
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "os_secs_left" in df.columns:
        df.loc[df["os_secs_left"] >= UNKNOWN_ESTIMATE, "os_secs_left"] = float("nan")
    return df.sort_values("timestamp").reset_index(drop=True)


def split_sessions(df, max_gap_s=120):
    """Label each row with a session number and state.

    A new session starts when the charger is plugged/unplugged, or when there is
    a gap longer than max_gap_s (the laptop slept, hibernated, or the logger stopped).
    """
    df = df.copy()
    gap = df["timestamp"].diff().dt.total_seconds()
    plug_change = df["plugged"].ne(df["plugged"].shift())
    new_session = plug_change | (gap > max_gap_s)
    new_session.iloc[0] = True
    df["session"] = new_session.cumsum()
    df["state"] = df["plugged"].map({0: "discharging", 1: "charging"})
    return df


def sessions(df, state=None, min_rows=2):
    """Yield (session_id, rows) for each session, optionally only one state."""
    if "session" not in df.columns:
        df = split_sessions(df)
    for sid, rows in df.groupby("session"):
        if len(rows) < min_rows:
            continue
        if state and rows["state"].iloc[0] != state:
            continue
        yield sid, rows.reset_index(drop=True)


def gaps(df, max_gap_s=120):
    """Find periods where no data was logged (sleep, hibernate, logger stopped).

    Returns a DataFrame with start, end, duration, and how much charge was lost.
    """
    df = df.reset_index(drop=True)
    gap_s = df["timestamp"].diff().dt.total_seconds()
    rows = []
    for i in df.index[gap_s > max_gap_s]:
        before, after = df.loc[i - 1], df.loc[i]
        hours = gap_s[i] / 3600
        lost_mwh = before["remaining_mwh"] - after["remaining_mwh"]
        rows.append({
            "start": before["timestamp"],
            "end": after["timestamp"],
            "hours": round(hours, 2),
            "percent_before": before["percent"],
            "percent_after": after["percent"],
            "lost_mwh": lost_mwh,
            "avg_drain_mw": round(lost_mwh / hours) if hours > 0 else None,
            "plugged": int(before["plugged"]),
        })
    return pd.DataFrame(rows)
