"""
Wind speed -> power for Irish wind farms.

Two pieces:
  1. fetch_era5()   pulls hourly 100 m wind speed at each farm from Open-Meteo's
                    ERA5 archive (no API key). Cached to disk so it runs once.
  2. power_curve()  converts wind speed to a fraction of rated capacity.

IMPORTANT CAVEATS, state these on any slide that uses this:
  * ERA5 is a REANALYSIS, not a forecast. Using it to "predict" is hindcasting.
    Open-Meteo's /v1/forecast endpoint is the real forecast if you need one.
  * ERA5's grid is ~0.25 deg (~28 km), so nearby farms share a grid cell and
    their modelled wind will be identical. That inflates spatial correlation.
  * The power curve is a GENERIC IEC-style curve, not the real turbine model at
    each site. Per-turbine curves are not public. Treat output as indicative.
"""

from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"
import csv
import json
import os
import time
import urllib.parse
import urllib.request

import numpy as np

FARMS = str(OUT_DIR / "wind-farms-with-coordinates.csv")
CACHE = str(DATA / "era5_wind_july2025.json")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# July 2025 matches the period of the Nayer network model's time series.
# Pass a different month on the command line to compare seasons, e.g.
#     python wind_power.py 2025-01-01 2025-01-31
# July is Ireland's LOW-wind season, so a winter month is the fair comparison.
START, END = "2025-07-01", "2025-07-31"
BATCH = 25

# Generic onshore turbine, IEC-style. Not site-specific.
CUT_IN, RATED, CUT_OUT = 3.0, 12.0, 25.0


def power_curve(v, cut_in=CUT_IN, rated=RATED, cut_out=CUT_OUT):
    """Fraction of rated capacity (0..1) for wind speed v in m/s.

    Below cut-in the turbine does not turn; between cut-in and rated the
    available power goes as v^3 (P = 1/2 rho A Cp v^3), so we ramp on the cube
    and normalise; above rated the machine is capped; above cut-out it shuts
    down to protect itself, which is why the curve drops to zero rather than
    continuing to rise.
    """
    v = np.asarray(v, dtype=float)
    out = np.zeros_like(v)
    ramp = (v >= cut_in) & (v < rated)
    out[ramp] = (v[ramp] ** 3 - cut_in ** 3) / (rated ** 3 - cut_in ** 3)
    out[(v >= rated) & (v < cut_out)] = 1.0
    return np.clip(out, 0.0, 1.0)


def shear(v_ref, h_target, h_ref=100.0, alpha=0.14):
    """Power-law extrapolation to a different hub height.

    alpha ~ 0.14 is the usual open-terrain value; ~0.11 offshore, ~0.20 over
    complex or forested terrain. ERA5 already gives 100 m, so this is only
    needed if a farm's hub height differs materially.
    """
    return np.asarray(v_ref, dtype=float) * (h_target / h_ref) ** alpha


def load_farms():
    with open(FARMS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_era5(farms, force=False):
    """Hourly 100 m wind speed per farm. Cached; batched to be polite."""
    if os.path.exists(CACHE) and not force:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)

    times, series = None, {}
    for i in range(0, len(farms), BATCH):
        chunk = farms[i:i + BATCH]
        q = urllib.parse.urlencode({
            "latitude": ",".join(f["lat"] for f in chunk),
            "longitude": ",".join(f["lon"] for f in chunk),
            "start_date": START, "end_date": END,
            "hourly": "wind_speed_100m", "wind_speed_unit": "ms",
        })
        with urllib.request.urlopen(f"{ARCHIVE}?{q}", timeout=120) as r:
            payload = json.load(r)
        # Multi-location queries return a list; a single location returns a dict.
        blocks = payload if isinstance(payload, list) else [payload]
        for farm, blk in zip(chunk, blocks):
            times = times or blk["hourly"]["time"]
            series[farm["farm"]] = blk["hourly"]["wind_speed_100m"]
        print(f"  fetched {min(i + BATCH, len(farms))}/{len(farms)}")
        time.sleep(1.0)

    data = {"times": times, "wind_100m": series, "start": START, "end": END}
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def main(start=None, end=None):
    global START, END, CACHE
    if start and end:
        START, END = start, end
        CACHE = str(DATA / f"era5_wind_{START}_{END}.json")
    farms = load_farms()
    print(f"farms: {len(farms)}")
    data = fetch_era5(farms)
    keep = [f for f in farms if f["farm"] in data["wind_100m"]]
    names = [f["farm"] for f in keep]
    W = np.nan_to_num(np.array([data["wind_100m"][n] for n in names], float))  # farms x hours
    mec = np.array([float(f["mec_mw"]) for f in keep])

    CF = power_curve(W)                 # capacity factor per farm per hour
    P = CF * mec[:, None]               # MW per farm per hour

    print(f"\nshape: {W.shape[0]} farms x {W.shape[1]} hours ({START}..{END})")
    print(f"mean wind speed 100m : {W.mean():.2f} m/s")
    print(f"fleet mean capacity factor : {CF.mean():.3f}")
    print(f"fleet total MEC : {mec.sum():.0f} MW")
    print(f"fleet mean output : {P.sum(axis=0).mean():.0f} MW")

    # Files are named by the period they cover, so runs never overwrite each other.
    tag = START[:7]
    np.save(str(OUT_DIR / f"wind-speed-100m-{tag}.npy"), W)
    np.save(str(OUT_DIR / f"wind-power-mw-{tag}.npy"), P)
    # A CSV, not a newline-delimited list: some SEAI farm names span two lines.
    with open(str(OUT_DIR / "wind-farm-row-order.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["farm"])
        w.writerows([[n] for n in names])
    print("\nsaved: data/wind-speed-100m-2025-07.npy, data/wind-power-mw-2025-07.npy, data/wind-farm-row-order.csv")
    return names, W, P, mec


if __name__ == "__main__":
    import sys as _sys
    a = _sys.argv[1:]
    main(a[0], a[1]) if len(a) == 2 else main()
