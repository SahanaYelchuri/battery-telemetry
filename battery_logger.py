"""
battery_logger.py - log Windows laptop battery telemetry to a CSV file.

What it records every few seconds:
  - battery % and Windows' own "time remaining" estimate (this is the gas gauge prediction)
  - whether the charger is plugged in
  - CPU load (so you can see how load affects drain and voltage)
  - raw battery data from the battery driver: remaining capacity (mWh),
    full-charge capacity, design capacity, voltage (mV), charge/discharge rate (mW)

Setup (once):
    pip install psutil

Run (one per laptop, give each a different label):
    python battery_logger.py --label personal
    python battery_logger.py --label work --interval 15

Quick check that everything works:
    python battery_logger.py --label test --once

Stop with Ctrl+C. Output goes to data/<label>_<date>.csv
"""

import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import time

try:
    import psutil
except ImportError:
    sys.exit("psutil is not installed. Run:  pip install psutil")

# PowerShell query for the raw battery driver data (root/wmi namespace).
# Any field the laptop doesn't report comes back empty instead of crashing.
PS_QUERY = r"""
$s = Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus -ErrorAction SilentlyContinue | Select-Object -First 1
$f = Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity -ErrorAction SilentlyContinue | Select-Object -First 1
$d = Get-CimInstance -Namespace root/wmi -ClassName BatteryStaticData -ErrorAction SilentlyContinue | Select-Object -First 1
[pscustomobject]@{
  remaining_mwh     = $s.RemainingCapacity
  voltage_mv        = $s.Voltage
  discharge_rate_mw = $s.DischargeRate
  charge_rate_mw    = $s.ChargeRate
  full_charge_mwh   = $f.FullChargedCapacity
  design_mwh        = $d.DesignedCapacity
} | ConvertTo-Json -Compress
"""

FIELDS = [
    "timestamp", "elapsed_s", "label",
    "percent", "os_secs_left", "plugged", "cpu_percent",
    "remaining_mwh", "full_charge_mwh", "design_mwh",
    "voltage_mv", "discharge_rate_mw", "charge_rate_mw",
]

DRIVER_KEYS = ["remaining_mwh", "full_charge_mwh", "design_mwh",
               "voltage_mv", "discharge_rate_mw", "charge_rate_mw"]


def read_driver_data():
    """Raw battery numbers from the Windows battery driver. Empty dict if unavailable."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", PS_QUERY],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return json.loads(out) if out else {}
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        return {}


def read_sample(start, label):
    batt = psutil.sensors_battery()
    if batt is None:
        sys.exit("No battery found on this machine.")

    # psutil uses special constants when Windows has no estimate (e.g. while charging)
    # Windows also reports 4294967295 (0xFFFFFFFF) when it has no estimate yet.
    secs = batt.secsleft
    if (secs in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN)
            or secs is None or secs < 0 or secs >= 0xFFFFFFFF):
        secs = ""

    driver = read_driver_data()
    now = time.time()
    row = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "elapsed_s": round(now - start, 1),
        "label": label,
        "percent": batt.percent,
        "os_secs_left": secs,
        "plugged": int(bool(batt.power_plugged)),
        "cpu_percent": psutil.cpu_percent(interval=None),
    }
    for key in DRIVER_KEYS:
        value = driver.get(key)
        row[key] = "" if value is None else value
    return row


def main():
    parser = argparse.ArgumentParser(description="Log laptop battery telemetry to CSV.")
    parser.add_argument("--label", required=True, help="name for this laptop, e.g. personal or work")
    parser.add_argument("--interval", type=float, default=10, help="seconds between samples (default 10)")
    parser.add_argument("--outdir", default="data", help="folder for CSV files (default: data)")
    parser.add_argument("--once", action="store_true", help="take one sample, print it, and exit")
    args = parser.parse_args()

    psutil.cpu_percent(interval=None)  # first call primes the CPU counter
    start = time.time()

    if args.once:
        row = read_sample(start, args.label)
        for key in FIELDS:
            print(f"{key:>18}: {row[key]}")
        missing = [k for k in DRIVER_KEYS if row[k] == ""]
        if missing:
            print(f"\nNote: this laptop did not report {', '.join(missing)}. "
                  "Try running the terminal as Administrator. The rest still works.")
        return

    os.makedirs(args.outdir, exist_ok=True)
    path = os.path.join(args.outdir, f"{args.label}_{datetime.date.today()}.csv")
    is_new = not os.path.exists(path)

    print(f"Logging to {path} every {args.interval}s. Press Ctrl+C to stop.")
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        try:
            while True:
                row = read_sample(start, args.label)
                writer.writerow(row)
                f.flush()  # so data is saved even if the laptop dies
                left = f"{int(row['os_secs_left']) // 60} min left" if row["os_secs_left"] != "" else "no estimate"
                print(f"{row['timestamp']}  {row['percent']:>3}%  {left:>14}  "
                      f"cpu {row['cpu_percent']:>5}%  {row['voltage_mv'] or '-'} mV  "
                      f"{'plugged' if row['plugged'] else 'on battery'}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\nStopped. Data saved to {path}")


if __name__ == "__main__":
    main()
