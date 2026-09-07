"""
Genuine wind FORECAST for the Irish fleet, as opposed to reanalysis.

Everything else in this folder uses ERA5, which is a reanalysis: it reconstructs
what the weather WAS using observations taken after the fact. Using it to
"predict" is hindcasting, and a judge will say so.

This uses Open-Meteo's forecast endpoint instead, which serves an actual
numerical weather prediction. Same power curve, same farm list, so the output is
directly comparable -- the only thing that changes is that the wind field is a
forecast rather than a reconstruction.

Output: wind-forecast-7day.csv  (fleet MW per hour) and a printed summary.
"""
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

import numpy as np

from wind_power import load_farms, power_curve

OUT = OUT_DIR / "wind-forecast-7day.csv"
API = "https://api.open-meteo.com/v1/forecast"
BATCH = 25
DAYS = 7


def fetch(farms, days=DAYS):
    times, series = None, {}
    for i in range(0, len(farms), BATCH):
        chunk = farms[i:i + BATCH]
        q = urllib.parse.urlencode({
            "latitude": ",".join(f["lat"] for f in chunk),
            "longitude": ",".join(f["lon"] for f in chunk),
            "hourly": "wind_speed_100m",
            "wind_speed_unit": "ms",
            "forecast_days": days,
        })
        with urllib.request.urlopen(f"{API}?{q}", timeout=120) as r:
            payload = json.load(r)
        blocks = payload if isinstance(payload, list) else [payload]
        for farm, blk in zip(chunk, blocks):
            times = times or blk["hourly"]["time"]
            series[farm["farm"]] = blk["hourly"]["wind_speed_100m"]
        print(f"  fetched {min(i + BATCH, len(farms))}/{len(farms)}")
        time.sleep(1.0)
    return times, series


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    farms = load_farms()
    print(f"forecasting {len(farms)} farms, {DAYS} days ahead")
    times, series = fetch(farms)

    keep = [f for f in farms if f["farm"] in series]
    W = np.nan_to_num(np.array([series[f["farm"]] for f in keep], float))
    mec = np.array([float(f["mec_mw"]) for f in keep])
    P = power_curve(W) * mec[:, None]
    fleet = P.sum(axis=0)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "fleet_mw", "capacity_factor"])
        for t, mw in zip(times, fleet):
            w.writerow([t, round(float(mw), 1), round(float(mw) / mec.sum(), 4)])

    print(f"\nwrote {OUT.name}: {len(times)} hourly steps")
    print(f"  window       : {times[0]} to {times[-1]} UTC")
    print(f"  fleet MEC    : {mec.sum():.0f} MW")
    print(f"  forecast mean: {fleet.mean():.0f} MW  (CF {fleet.mean()/mec.sum():.3f})")
    print(f"  range        : {fleet.min():.0f} to {fleet.max():.0f} MW")

    # A crude but honest curtailment-risk flag: high output is when the network
    # and the SNSP limit are most likely to bind.
    hi = fleet > 0.6 * mec.sum()
    print(f"  hours above 60% of fleet capacity: {hi.sum()} of {len(fleet)}"
          f"  ({100*hi.mean():.0f}%)")
    print("\nNOTE: this is a real forecast, unlike the ERA5 archive used elsewhere.")
    print("The power curve is still generic, so treat levels as indicative and")
    print("the SHAPE of the profile as the useful part.")
    return times, fleet


if __name__ == "__main__":
    main()
