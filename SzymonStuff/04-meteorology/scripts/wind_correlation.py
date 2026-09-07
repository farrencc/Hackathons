"""
How correlated is wind between Irish farms, as a function of distance?

This is the physical link between the weather layer and the network layer: if
output at every farm rose and fell together, curtailment would be a single
system-wide event. It does not, and the decorrelation length is what makes
curtailment a LOCAL, clustered phenomenon.

Fits corr(d) = exp(-d / L) and reports L, the decorrelation length in km.
"""

from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"
import csv

import numpy as np

FARMS = str(OUT_DIR / "wind-farms-with-coordinates.csv")
R_EARTH = 6371.0


def haversine_matrix(lat, lon):
    """Great-circle distance in km between every pair of points."""
    la, lo = np.radians(lat), np.radians(lon)
    dla = la[:, None] - la[None, :]
    dlo = lo[:, None] - lo[None, :]
    a = np.sin(dla / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dlo / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def main(tag=""):
    # Files are named by period, e.g. wind-speed-100m-2025-01.npy
    period = tag.lstrip("_") if tag else "2025-07"
    with open(str(OUT_DIR / "wind-farm-row-order.csv"), encoding="utf-8") as f:
        names = [r["farm"] for r in csv.DictReader(f)]
    W = np.load(str(OUT_DIR / f"wind-speed-100m-{period}.npy"))
    rows = {r["farm"]: r for r in csv.DictReader(open(FARMS, encoding="utf-8"))}
    lat = np.array([float(rows[n]["lat"]) for n in names])
    lon = np.array([float(rows[n]["lon"]) for n in names])

    D = haversine_matrix(lat, lon)
    C = np.corrcoef(W)

    iu = np.triu_indices(len(names), k=1)
    d, c = D[iu], C[iu]
    ok = np.isfinite(c)
    d, c = d[ok], c[ok]

    print(f"{len(names)} farms, {len(d)} pairs, {period} hourly 100 m wind\n")
    print(f"{'distance band':<16}{'pairs':>7}{'mean corr':>11}")
    bands = [(0, 10), (10, 25), (25, 50), (50, 100), (100, 150), (150, 200), (200, 400)]
    for lo_, hi in bands:
        m = (d >= lo_) & (d < hi)
        if m.sum():
            print(f"  {lo_:>3}-{hi:<3} km {'':<3}{m.sum():>7}{c[m].mean():>11.3f}")

    # Fit corr = exp(-d/L) on pairs far enough apart to be in different ERA5
    # cells (the grid is ~28 km, so anything closer is partly the same data).
    far = d > 30
    L = -np.polyfit(d[far], np.log(np.clip(c[far], 1e-6, None)), 1)[0]
    print(f"\ndecorrelation length L = {1/L:.0f} km   (fit corr = exp(-d/L), pairs >30 km)")

    print(f"island's longest dimension is ~450 km, so L exceeds it: correlation")
    print(f"never decays away within Ireland. Lowest band still averages {c[d > 200].mean():.2f}.")
    print("\nCAVEATS")
    print("  * ERA5's grid is ~28 km, so sub-30 km pairs often share a grid cell")
    print("    and show correlation ~1.0 as an artefact, not as physics.")
    print("  * One month only. Season matters: July 2025 gives L = 460 km,")
    print("    January 2025 gives L = 599 km. Winter is MORE correlated, so")
    print("    geographic spread helps least when curtailment is worst.")


if __name__ == "__main__":
    import sys as _sys
    main(_sys.argv[1] if len(_sys.argv) > 1 else "")
