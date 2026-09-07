"""
Effectiveness under N-1: how much each farm relieves each line AFTER an outage.

WHY THIS AND NOT THE BASE CASE. EirGrid define a constraint group by
effectiveness against "the 'base case', 'N-1' or 'N-1-1' overload". Contingency
analysis is therefore inside the definition, not a refinement of it. A line
sitting at 60% of its rating may be perfectly safe today and completely
unacceptable, because if the parallel circuit trips this one inherits its flow
and overloads immediately. The binding limit is usually not the flow now, but
the flow after the worst credible single failure.

THE FORMULA. For a monitored line l, an injection at bus f, and an outage of
line k:

    PTDF_n1[l, f | k]  =  PTDF[l, f]  +  BODF[l, k] * PTDF[k, f]

Read it as: the flow that would have appeared on l anyway, plus the share of
line k's flow that lands on l once k is gone. Both terms come from matrices we
have already verified by hand (verify_ptdf.py 8/8, verify_bodf.py 5/5).

We then take, for each (line, farm), the contingency that produces the LARGEST
magnitude - the worst credible case, which is what security assessment means.

TWO EXCLUSIONS, BOTH NECESSARY

  * Radial outages. If removing line k splits the network, BODF is undefined and
    PyPSA returns non-finite values. Those contingencies are detected and
    skipped rather than allowed to poison the maximum.
  * k == l. A line's sensitivity to its own outage is meaningless: it is out, so
    it carries nothing.

Same distributed-slack correction as the base case, for the same reason - see
compute_effectiveness.py.

Outputs
    script-output/effectiveness-n1-farm-by-line.csv    worst-case (line, farm) pairs
    script-output/critical-contingencies.csv           which outages actually matter
"""
import csv
import sys
import warnings
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
OUT_DIR = FOLDER / "script-output"

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import pypsa

NET = OUT_DIR / "ireland-network.nc"
MAP = OUT_DIR / "farm-to-constraint-group-map.csv"
OUT_PAIRS = OUT_DIR / "effectiveness-n1-farm-by-line.csv"
OUT_CONT = OUT_DIR / "critical-contingencies.csv"
MATRIX = OUT_DIR / "effectiveness-n1-matrix.npy"
ORDER = OUT_DIR / "effectiveness-n1-order.csv"

THRESHOLD = 0.05


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    n = pypsa.Network(str(NET))
    n.determine_network_topology()
    sub = n.sub_networks.obj[n.buses.sub_network.value_counts().index[0]]
    sub.calculate_PTDF()
    sub.calculate_BODF()

    names = sub.branches_i().get_level_values(1).to_numpy()
    buses = sub.components.buses.static.index
    PTDF = pd.DataFrame(sub.PTDF, index=names, columns=buses)
    BODF = np.asarray(sub.BODF)
    nb = len(names)
    print(f"branches {nb}, buses {len(buses)}")

    # Contingencies whose removal splits the network have undefined BODF.
    valid = np.isfinite(BODF).all(axis=0)
    print(f"contingencies usable        : {valid.sum()} of {nb}")
    print(f"radial / network-splitting  : {(~valid).sum()} (excluded)")

    farms = pd.read_csv(MAP)
    farms = farms[(farms.matched == "yes") & farms.model_bus.isin(PTDF.columns)]
    farms = farms.reset_index(drop=True)
    Pw = PTDF[farms.model_bus.values].to_numpy()          # branches x farms
    farm_names = farms.farm.to_numpy()
    print(f"farms                       : {len(farms)}\n")

    # Worst single contingency per (line, farm), tracked with its sign and cause.
    worst = Pw.copy()                                     # start from base case
    worst_k = np.full(Pw.shape, -1, dtype=int)            # -1 means base case
    best = np.abs(Pw)

    print("scanning contingencies...")
    for k in np.nonzero(valid)[0]:
        cand = Pw + np.outer(BODF[:, k], Pw[k, :])
        cand[k, :] = Pw[k, :]                             # k is out: not monitored
        mag = np.abs(cand)
        better = mag > best
        if better.any():
            worst = np.where(better, cand, worst)
            worst_k = np.where(better, k, worst_k)
            best = np.where(better, mag, best)
    print("done\n")

    # Distributed slack, exactly as in the base case.
    cap = farms.mec_mw.fillna(0).to_numpy(float)
    w = cap / cap.sum() if cap.sum() else np.full(len(cap), 1 / len(cap))
    rel = worst - (worst @ w)[:, None]

    np.save(MATRIX, rel)
    with open(ORDER, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["axis", "index", "name"])
        wr.writerows([["line", i, s] for i, s in enumerate(names)])
        wr.writerows([["farm", i, s] for i, s in enumerate(farm_names)])

    rating = pd.concat([n.lines.s_nom, n.transformers.s_nom])
    mec = dict(zip(farms.farm, farms.mec_mw))
    groups = dict(zip(farms.farm, farms.groups_via_model))

    keep = np.abs(rel) >= THRESHOLD
    li, fi = np.nonzero(keep)
    rows = [{
        "line": names[a],
        "line_rating_mw": round(float(rating.get(names[a], np.nan)), 1),
        "farm": farm_names[b],
        "effectiveness_n1": round(float(rel[a, b]), 4),
        "abs_effectiveness_n1": round(abs(float(rel[a, b])), 4),
        "worst_contingency": names[worst_k[a, b]] if worst_k[a, b] >= 0 else "(base case)",
        "farm_mec_mw": mec.get(farm_names[b], ""),
        "prorata_groups": groups.get(farm_names[b], ""),
    } for a, b in zip(li, fi)]
    rows.sort(key=lambda r: -r["abs_effectiveness_n1"])

    with open(OUT_PAIRS, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    # Which outages actually drive the worst cases, weighted by wind at risk.
    tally = {}
    for a, b in zip(li, fi):
        k = worst_k[a, b]
        if k < 0:
            continue
        t = tally.setdefault(names[k], {"pairs": 0, "farms": set(), "lines": set()})
        t["pairs"] += 1
        t["farms"].add(farm_names[b])          # distinct, so capacity is not double-counted
        t["lines"].add(names[a])
    for t in tally.values():
        t["wind_mw"] = sum(float(mec.get(f, 0) or 0) for f in t["farms"])
    cont = sorted(tally.items(), key=lambda kv: -kv[1]["wind_mw"])
    with open(OUT_CONT, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["contingency", "rating_mw", "pairs_worsened", "lines_affected",
                     "distinct_farms", "distinct_wind_mw"])
        for name, t in cont:
            wr.writerow([name, round(float(rating.get(name, np.nan)), 1),
                         t["pairs"], len(t["lines"]), len(t["farms"]),
                         round(t["wind_mw"], 1)])

    base_n = int((np.abs(Pw - (Pw @ w)[:, None]) >= THRESHOLD).sum())
    print(f"(line, farm) pairs above {THRESHOLD}:")
    print(f"   base case : {base_n:,}")
    print(f"   under N-1 : {len(rows):,}   ({100*(len(rows)-base_n)/base_n:+.0f}%)")
    print(f"pairs whose worst case IS a contingency: "
          f"{sum(1 for r in rows if r['worst_contingency'] != '(base case)'):,}")

    print("\nContingencies putting the most wind capacity at risk:")
    print("  (distinct farms, so capacity is never double-counted)")
    print(f"  {'outage':<32}{'rating':>8}{'lines':>7}{'farms':>7}{'wind MW':>9}")
    for name, t in cont[:10]:
        print(f"  {name[:31]:<32}{rating.get(name, float('nan')):>8.0f}"
              f"{len(t['lines']):>7}{len(t['farms']):>7}{t['wind_mw']:>9.0f}")

    print(f"\nwrote {OUT_PAIRS.name}, {OUT_CONT.name}, {MATRIX.name}")
    return rows, cont


if __name__ == "__main__":
    main()
