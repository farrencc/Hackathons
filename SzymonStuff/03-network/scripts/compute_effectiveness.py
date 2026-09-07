"""
Compute each wind farm's effectiveness against every transmission line.

This is EirGrid's own definition of a constraint group, recomputed from the
network they operate:

    "Wind/solar farms are grouped together depending on their EFFECTIVENESS to
     alleviate constraints... a measure of the change in wind/solar farm output
     relative to the change in the level of the overload. The effectiveness of
     each wind/solar farm is a function of the TOPOLOGY of the transmission
     network."

That quantity is a Power Transfer Distribution Factor. PTDF[line, bus] is the
fraction of 1 MW injected at `bus` that ends up flowing along `line`. So a farm
with a large PTDF against a congested line is highly effective at relieving it,
and one with a PTDF near zero cannot help however far it is dispatched down.

THE REFERENCE BUS, AND WHY TWO COLUMNS ARE REPORTED. Power injected somewhere
must be withdrawn somewhere. PyPSA's raw PTDF assumes the balancing withdrawal
happens at the sub-network's slack bus - here CPS_N_Z_110 in Northern Ireland.
That makes every line near the slack look highly exposed to every farm in
Ireland, which is an artefact of the reference, not a property of the grid.

So we report two numbers:

  effectiveness            the raw slack-referenced PTDF
  effectiveness_vs_fleet   the same, minus the capacity-weighted fleet average
                           for that line

The second is a distributed-slack PTDF in which the balancing MW is shared
across the wind fleet in proportion to capacity - which is exactly how EirGrid
share a pro-rata reduction within a group. It cancels the arbitrary slack and
answers the question grouping actually asks: relative to the rest of the fleet,
how much does THIS farm move THIS line? Use it for clustering.

Verified first: run verify_ptdf.py, which checks this machinery against a
three-bus network solvable by hand. It passes 8/8.

Outputs
    script-output/effectiveness-farm-by-line.csv   long format, one row per
        (line, farm) pair above a threshold - the full matrix is too large
    script-output/line-effectiveness-summary.csv   each line's rating and how
        many farms can materially influence it
"""
import csv
import sys
import warnings
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import pypsa

NET = OUT_DIR / "ireland-network.nc"
MAP = OUT_DIR / "farm-to-constraint-group-map.csv"
OUT_PAIRS = OUT_DIR / "effectiveness-farm-by-line.csv"
OUT_LINES = OUT_DIR / "line-effectiveness-summary.csv"

# Below this a farm's influence on a line is negligible; EirGrid exclude farms
# that "do not substantially help relieve a given overload" for the same reason.
# Applied to the fleet-relative measure, not the raw slack-referenced one.
THRESHOLD = 0.05


def ptdf_frame(n):
    """PTDF for the main sub-network, as branches x buses."""
    n.determine_network_topology()
    sizes = n.buses.sub_network.value_counts()
    main = sizes.index[0]
    sub = n.sub_networks.obj[main]
    sub.calculate_PTDF()
    branches = sub.branches_i()
    return pd.DataFrame(sub.PTDF,
                        index=branches.get_level_values(1),
                        columns=sub.components.buses.static.index), branches


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    n = pypsa.Network(str(NET))
    P, branches = ptdf_frame(n)
    print(f"PTDF computed: {P.shape[0]} branches x {P.shape[1]} buses")

    # Which buses carry wind, and which farms sit on them.
    farms = pd.read_csv(MAP)
    farms = farms[(farms.matched == "yes") & farms.model_bus.notna()]
    farms = farms[farms.model_bus.isin(P.columns)]
    print(f"wind farms placed on buses in this sub-network: {len(farms)}")

    # Ratings, so effectiveness can be read against real thermal limits.
    rating = pd.concat([n.lines.s_nom, n.transformers.s_nom])
    kind = pd.Series(branches.get_level_values(0), index=P.index)

    # Long format: one row per (line, farm) where the farm matters.
    rows = []
    Pw = P[farms.model_bus.values]
    Pw.columns = farms.farm.values
    arr = Pw.to_numpy()
    keep = np.abs(arr) >= THRESHOLD
    line_names = P.index.to_numpy()
    farm_names = Pw.columns.to_numpy()
    mec = farms.set_index("farm").mec_mw.to_dict()
    groups = farms.set_index("farm").groups_via_model.to_dict()

    # Distributed slack: subtract the capacity-weighted fleet mean per line, so
    # the arbitrary choice of slack bus cancels out.
    cap = farms.set_index("farm").mec_mw.reindex(farm_names).fillna(0).to_numpy(float)
    weights = cap / cap.sum() if cap.sum() > 0 else np.full(len(cap), 1 / len(cap))
    fleet_mean = arr @ weights                      # one value per line
    rel = arr - fleet_mean[:, None]

    # Selection now uses the fleet-relative measure, which is the meaningful one.
    keep = np.abs(rel) >= THRESHOLD
    li, fi = np.nonzero(keep)
    for a, b in zip(li, fi):
        rows.append({
            "line": line_names[a],
            "line_type": kind.iloc[a],
            "line_rating_mw": round(float(rating.get(line_names[a], np.nan)), 1),
            "farm": farm_names[b],
            "effectiveness": round(float(arr[a, b]), 4),
            "effectiveness_vs_fleet": round(float(rel[a, b]), 4),
            "abs_effectiveness": round(abs(float(rel[a, b])), 4),
            "farm_mec_mw": mec.get(farm_names[b], ""),
            "prorata_groups": groups.get(farm_names[b], ""),
        })
    rows.sort(key=lambda r: -r["abs_effectiveness"])

    with open(OUT_PAIRS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # Per-line summary: how many farms can move this line, and by how much.
    n_eff = keep.sum(axis=1)
    max_eff = np.abs(rel).max(axis=1)
    mw_eff = np.array([sum(float(mec.get(farm_names[b], 0) or 0)
                           for b in np.nonzero(keep[a])[0]) for a in range(len(line_names))])
    summary = pd.DataFrame({
        "line": line_names,
        "line_type": kind.values,
        "rating_mw": [rating.get(l, np.nan) for l in line_names],
        "n_farms_effective": n_eff,
        "wind_mw_effective": mw_eff.round(1),
        "max_effectiveness": max_eff.round(4),
    }).sort_values("wind_mw_effective", ascending=False)
    summary.to_csv(OUT_LINES, index=False)

    print(f"\n(line, farm) pairs with |effectiveness| >= {THRESHOLD}: {len(rows):,}")
    print(f"lines with at least one effective farm: {(n_eff > 0).sum()} of {len(line_names)}")

    print("\nLines most exposed to wind (most effective capacity behind them):")
    print(f"  {'line':<34}{'rating':>8}{'farms':>7}{'wind MW':>9}{'max eff':>9}")
    for _, r in summary.head(10).iterrows():
        print(f"  {r.line[:33]:<34}{r.rating_mw:>8.0f}{r.n_farms_effective:>7.0f}"
              f"{r.wind_mw_effective:>9.0f}{r.max_effectiveness:>9.3f}")

    print("\nStrongest single farm-line couplings:")
    for r in rows[:8]:
        print(f"  {r['effectiveness_vs_fleet']:+.3f}  {r['farm'][:30]:<30}"
              f" -> {r['line'][:32]}")

    print(f"\nwrote {OUT_PAIRS.name}, {OUT_LINES.name}")
    return summary, rows


if __name__ == "__main__":
    main()
