"""
Estimate per-farm curtailment at hourly resolution -- a figure nobody publishes.

The ingredients:
  * EirGrid publishes Irish wind AVAILABILITY and GENERATION every 15 minutes.
    Their difference is total dispatch-down, measured, at high resolution.
  * Our wind model reproduces that availability at r-squared 0.97 (see
    04-meteorology/validate_against_eirgrid.py), per farm.

Combining them attributes the measured total to individual farms.

THE ATTRIBUTION RULE, AND ITS LIMIT. EirGrid reduce output pro-rata within a
group, and system-wide curtailment is applied pro-rata across the fleet. So
splitting dispatch-down in proportion to each farm's available output is
faithful to their method FOR CURTAILMENT. It is wrong for CONSTRAINT, which is
local: a bottleneck in Mayo does not curtail a farm in Wexford. Since constraint
is now the larger half of dispatch-down, this estimate spreads localised
constraint too evenly.

That is not a flaw to hide, it is the motivation for the next step: computing
line-flow sensitivity (PTDF) tells you WHICH farms relieve WHICH bottleneck, and
replaces the flat pro-rata split with a physical one.

Output: curtailment-per-farm-2026.csv, curtailment-per-group-2026.csv
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

ROOT = ROOT
MET = ROOT / "04-meteorology" / "script-output"
MET_SCRIPTS = ROOT / "04-meteorology" / "scripts"
OBS = ROOT / "02-curtailment" / "script-output" / "system-state-15min-2026.csv"
MAP = ROOT / "03-network" / "script-output" / "farm-to-constraint-group-map.csv"

START, END = "2026-01-01", "2026-07-31"


def observed_hourly():
    """IE availability and generation, 15-min -> hourly mean, keyed 'YYYY-MM-DDTHH'."""
    av, gen = defaultdict(list), defaultdict(list)
    with open(OBS, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            a, g = r.get("IE Wind Availability"), r.get("IE Wind Generation")
            if not a or not g:
                continue
            k = r["DateTime"][:13].replace(" ", "T")
            av[k].append(float(a))
            gen[k].append(float(g))
    return ({k: sum(v) / len(v) for k, v in av.items()},
            {k: sum(v) / len(v) for k, v in gen.items()})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    sys.path.insert(0, str(MET_SCRIPTS))
    import wind_power
    wind_power.START, wind_power.END = START, END
    wind_power.CACHE = str(ROOT / "04-meteorology" / "data" / f"era5_wind_{START}_{END}.json")
    farms = wind_power.load_farms()
    data = wind_power.fetch_era5(farms)

    keep = [f for f in farms if f["farm"] in data["wind_100m"]]
    names = [f["farm"] for f in keep]
    W = np.nan_to_num(np.array([data["wind_100m"][n] for n in names], float))
    mec = np.array([float(f["mec_mw"]) for f in keep])
    model = wind_power.power_curve(W) * mec[:, None]        # farms x hours

    av, gen = observed_hourly()
    times = data["times"]
    cols = [i for i, t in enumerate(times) if t[:13] in av]
    model = model[:, cols]
    stamp = [times[i] for i in cols]
    obs_av = np.array([av[t[:13]] for t in stamp])
    obs_dd = np.array([max(av[t[:13]] - gen[t[:13]], 0.0) for t in stamp])

    # Pro-rata: each farm carries dispatch-down in proportion to its share of
    # modelled available output in that hour.
    share = np.divide(model, model.sum(axis=0, keepdims=True),
                      out=np.zeros_like(model),
                      where=model.sum(axis=0, keepdims=True) > 0)
    dd_farm = share * obs_dd[None, :]                        # MW per farm per hour
    mwh = dd_farm.sum(axis=1)                                # hourly steps -> MWh
    avail_mwh = model.sum(axis=1)

    with open(MAP, encoding="utf-8") as f:
        info = {r["farm"]: r for r in csv.DictReader(f)}

    rows = []
    for i, n in enumerate(names):
        r = info.get(n, {})
        rows.append({
            "farm": n,
            "county": r.get("county", ""),
            "mec_mw": round(mec[i], 2),
            "model_bus": r.get("model_bus", ""),
            "prorata_groups": r.get("groups_via_model", ""),
            "available_mwh": round(float(avail_mwh[i]), 1),
            "curtailed_mwh": round(float(mwh[i]), 1),
            "curtailed_pct": round(100 * float(mwh[i] / avail_mwh[i]), 2) if avail_mwh[i] else "",
        })
    rows.sort(key=lambda r: -r["curtailed_mwh"])
    with open(OUT_DIR / "curtailment-per-farm-2026.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # Roll up to constraint group. A farm in several groups contributes to each,
    # so these totals overlap by construction and must not be summed.
    grp = defaultdict(lambda: [0.0, 0.0, 0])
    for r in rows:
        for g in (r["prorata_groups"] or "").split(";"):
            if g:
                grp[g][0] += r["curtailed_mwh"]
                grp[g][1] += r["available_mwh"]
                grp[g][2] += 1
    with open(OUT_DIR / "curtailment-per-group-2026.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "n_farms", "available_mwh", "curtailed_mwh", "curtailed_pct"])
        for g, (c, a, n) in sorted(grp.items(), key=lambda kv: -kv[1][0]):
            w.writerow([g, n, round(a, 1), round(c, 1), round(100 * c / a, 2) if a else ""])

    tot_dd = float(obs_dd.sum())
    print(f"period            : {stamp[0]} to {stamp[-1]}  ({len(stamp)} hours)")
    print(f"measured dispatch-down (Ireland) : {tot_dd/1000:>9.0f} GWh")
    print(f"modelled availability            : {model.sum()/1000:>9.0f} GWh")
    print(f"observed availability            : {obs_av.sum()/1000:>9.0f} GWh")
    print(f"implied dispatch-down rate       : {100*tot_dd/obs_av.sum():>8.1f}%\n")

    print("Most-curtailed farms (MWh, pro-rata estimate):")
    for r in rows[:10]:
        print(f"  {r['curtailed_mwh']:>8.0f} MWh  {r['curtailed_pct']:>5.1f}%  "
              f"{r['farm'][:34]:<34} {r['county'][:10]}")

    print("\nMost-exposed constraint groups (overlapping, do not sum):")
    for g, (c, a, n) in sorted(grp.items(), key=lambda kv: -kv[1][0])[:8]:
        print(f"  {c/1000:>7.1f} GWh  {100*c/a:>5.1f}%  {g:<12} {n:>3} farms")

    print("\nCAVEAT: pro-rata across the whole fleet is EirGrid's rule for")
    print("CURTAILMENT but not for CONSTRAINT, which is local. This therefore")
    print("spreads localised constraint too evenly. PTDF is what fixes it.")


if __name__ == "__main__":
    main()
