"""
Does our wind model reproduce what EirGrid actually measured?

Everything else in this folder is a MODEL: ERA5 wind speeds pushed through a
generic power curve. This script is the only place that model meets observation.

EirGrid publishes "IE Wind Availability" at 15-minute resolution -- the metered
figure for how much wind COULD have been produced (before any dispatch-down).
That is exactly the quantity our pipeline estimates, so the two are directly
comparable. Availability, not generation: generation is availability minus
curtailment, and our model knows nothing about curtailment.

Output: model-vs-eirgrid-hourly-2026.csv and a printed skill summary.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

import numpy as np

from wind_power import fetch_era5, load_farms, power_curve

OBS = ROOT / "02-curtailment" / "script-output" / "system-state-15min-2026.csv"
OUT = OUT_DIR / "model-vs-eirgrid-hourly-2026.csv"

START, END = "2026-01-01", "2026-07-31"


def observed_hourly():
    """EirGrid IE wind availability, 15-min -> hourly mean, keyed by 'YYYY-MM-DDTHH'."""
    buckets = defaultdict(list)
    with open(OBS, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            v = r.get("IE Wind Availability")
            if not v:
                continue
            # '2026-01-01 00:15:00' -> '2026-01-01T00'
            key = r["DateTime"][:13].replace(" ", "T")
            buckets[key].append(float(v))
    return {k: sum(v) / len(v) for k, v in buckets.items()}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    import wind_power
    wind_power.START, wind_power.END = START, END
    wind_power.CACHE = str(DATA / f"era5_wind_{START}_{END}.json")

    farms = load_farms()
    print(f"modelling {len(farms)} farms, {START}..{END}")
    data = fetch_era5(farms)

    keep = [f for f in farms if f["farm"] in data["wind_100m"]]
    W = np.nan_to_num(np.array([data["wind_100m"][f["farm"]] for f in keep], float))
    mec = np.array([float(f["mec_mw"]) for f in keep])
    modelled = (power_curve(W) * mec[:, None]).sum(axis=0)   # fleet MW per hour

    obs = observed_hourly()
    times = data["times"]
    pairs = [(t, m, obs[t[:13]]) for t, m in zip(times, modelled) if t[:13] in obs]
    print(f"matched {len(pairs)} hourly points against EirGrid\n")

    t = [p[0] for p in pairs]
    mod = np.array([p[1] for p in pairs])
    act = np.array([p[2] for p in pairs])

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "modelled_mw", "eirgrid_observed_mw"])
        for a, b, c in zip(t, mod, act):
            w.writerow([a, round(float(b), 1), round(float(c), 1)])

    r = float(np.corrcoef(mod, act)[0, 1])
    bias = float(mod.mean() - act.mean())
    rmse = float(np.sqrt(((mod - act) ** 2).mean()))
    mae = float(np.abs(mod - act).mean())
    cap = mec.sum()

    print(f"{'':<26}{'modelled':>10}{'EirGrid':>10}")
    print(f"{'mean output (MW)':<26}{mod.mean():>10.0f}{act.mean():>10.0f}")
    print(f"{'peak output (MW)':<26}{mod.max():>10.0f}{act.max():>10.0f}")
    print(f"{'capacity factor':<26}{mod.mean()/cap:>10.3f}{act.mean()/cap:>10.3f}")
    print(f"\ncorrelation r      : {r:.3f}   (r^2 = {r**2:.3f})")
    print(f"bias               : {bias:+.0f} MW  ({100*bias/act.mean():+.1f}% of observed mean)")
    print(f"RMSE               : {rmse:.0f} MW  ({100*rmse/cap:.1f}% of fleet capacity)")
    print(f"MAE                : {mae:.0f} MW")
    print(f"\nwrote {OUT.name}")
    print("\nWhat this does and does not show:")
    print("  * It compares AVAILABILITY, so it tests the weather-to-power model only.")
    print("  * The farm list is SEAI June 2022, so it misses capacity connected since.")
    print("  * The power curve is generic, so a level bias is expected; the")
    print("    correlation is the part that says whether the physics tracks.")
    return r, bias, rmse


if __name__ == "__main__":
    main()
