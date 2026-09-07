"""
Aggregate per-farm wind output onto network buses.

The meteorology folder produces wind power per FARM. Power flow needs injection
per BUS. This bridges the two using the farm-to-generator-to-bus mapping built in
03-network, and is the input any PTDF or DC-OPF work will need.

Only farms matched to a model generator can be placed on a bus, so the total here
is less than the full fleet. That shortfall is reported rather than hidden.

Output: wind-by-bus-summary-2025-07.csv  (one row per bus, one column per hour is too
wide to be useful, so this writes the summary; the full matrix is saved as .npy)
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
MAP = ROOT / "03-network" / "script-output" / "farm-to-constraint-group-map.csv"
MET = ROOT / "04-meteorology" / "script-output"
OUT = OUT_DIR / "wind-by-bus-summary-2025-07.csv"
MATRIX = OUT_DIR / "wind-by-bus-matrix-2025-07.npy"
ORDER = OUT_DIR / "wind-by-bus-row-order.csv"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(MET / "wind-farm-row-order.csv", encoding="utf-8") as f:
        farm_order = [r["farm"] for r in csv.DictReader(f)]
    P = np.load(MET / "wind-power-mw-2025-07.npy")          # farms x hours, July 2025
    row_of = {name: i for i, name in enumerate(farm_order)}

    with open(MAP, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    bus_rows = defaultdict(list)
    bus_mw = defaultdict(float)
    bus_groups = {}
    placed_mw = unplaced_mw = 0.0
    for r in rows:
        mw = float(r["mec_mw"])
        if r["matched"] != "yes" or not r["model_bus"] or r["farm"] not in row_of:
            unplaced_mw += mw
            continue
        bus = r["model_bus"]
        bus_rows[bus].append(row_of[r["farm"]])
        bus_mw[bus] += mw
        bus_groups.setdefault(bus, r["groups_via_model"])
        placed_mw += mw

    buses = sorted(bus_rows)
    M = np.vstack([P[bus_rows[b], :].sum(axis=0) for b in buses])   # buses x hours

    np.save(MATRIX, M)
    with open(ORDER, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bus"])
        w.writerows([[b] for b in buses])

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bus", "n_farms", "capacity_mw", "mean_mw", "peak_mw",
                    "capacity_factor", "prorata_groups"])
        for i, b in enumerate(buses):
            cap = bus_mw[b]
            w.writerow([b, len(bus_rows[b]), round(cap, 2),
                        round(float(M[i].mean()), 2), round(float(M[i].max()), 2),
                        round(float(M[i].mean() / cap), 4) if cap else "",
                        bus_groups[b]])

    print(f"buses carrying wind : {len(buses)}")
    print(f"farms placed        : {sum(len(v) for v in bus_rows.values())}")
    print(f"capacity placed     : {placed_mw:.0f} MW")
    print(f"capacity unplaced   : {unplaced_mw:.0f} MW "
          f"({100*unplaced_mw/(placed_mw+unplaced_mw):.0f}% of the fleet)")
    print(f"matrix              : {M.shape[0]} buses x {M.shape[1]} hours\n")

    top = sorted(range(len(buses)), key=lambda i: -bus_mw[buses[i]])[:8]
    print("largest wind buses:")
    for i in top:
        print(f"  {buses[i]:<16} {bus_mw[buses[i]]:>7.1f} MW  "
              f"{len(bus_rows[buses[i]]):>2} farms   {bus_groups[buses[i]][:34]}")
    print(f"\nwrote {OUT.name}, {MATRIX.name}, {ORDER.name}")
    return buses, M


if __name__ == "__main__":
    main()
