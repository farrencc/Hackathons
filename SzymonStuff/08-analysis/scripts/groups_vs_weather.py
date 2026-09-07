"""
Are EirGrid's constraint groups just geography in disguise?

Farms in the same constraint group sit near each other, so of course their wind
is correlated. The real question is whether they are correlated MORE than any
other pair of farms the same distance apart. If not, the grouping carries no
weather information beyond proximity -- which would mean it encodes network
topology, exactly as EirGrid describe it.

Method, following the workshop capstone: measure a quantity across a proposed
partition, then test it against a null that holds constant everything you do not
care about. Here the null is distance: we predict each pair's correlation from
its separation alone, and ask whether same-group pairs beat that prediction.

Output: groups-vs-weather-test.csv
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
MAP = ROOT / "03-network" / "script-output" / "farm-to-constraint-group-map.csv"
OUT = OUT_DIR / "groups-vs-weather-test.csv"

RNG = np.random.default_rng(0)
DRAWS = 500


def haversine(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    dla, dlo = la[:, None] - la[None, :], lo[:, None] - lo[None, :]
    a = np.sin(dla / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dlo / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(MET / "wind-farm-row-order.csv", encoding="utf-8") as f:
        names = [r["farm"] for r in csv.DictReader(f)]
    idx = {n: i for i, n in enumerate(names)}
    with open(MET / "wind-farms-with-coordinates.csv", encoding="utf-8") as f:
        loc = {r["farm"]: r for r in csv.DictReader(f)}

    W = np.load(MET / "wind-speed-100m-2025-07.npy")
    Corr = np.corrcoef(W)
    D = haversine(np.array([float(loc[n]["lat"]) for n in names]),
                  np.array([float(loc[n]["lon"]) for n in names]))

    # Predict correlation from distance alone: exp(-d/L) fitted on all pairs
    # more than 30 km apart (closer pairs share an ERA5 grid cell).
    iu = np.triu_indices(len(names), k=1)
    d_all, c_all = D[iu], Corr[iu]
    far = d_all > 30
    L = 1.0 / -np.polyfit(d_all[far], np.log(np.clip(c_all[far], 1e-6, None)), 1)[0]
    predict = lambda d: np.exp(-d / L)
    print(f"distance-only model: corr = exp(-d / {L:.0f} km)\n")

    # Group membership, from the model's prorata_groups.
    members = defaultdict(set)
    with open(MAP, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["matched"] != "yes" or r["farm"] not in idx:
                continue
            for g in r["groups_via_model"].split(";"):
                if g and g != "ROI/1":        # nationwide group is not a locality
                    members[g].add(idx[r["farm"]])

    out = []
    for g, ms in sorted(members.items()):
        m = sorted(ms)
        if len(m) < 4:
            continue
        pairs = [(i, j) for a, i in enumerate(m) for j in m[a + 1:]]
        obs = float(np.mean([Corr[i, j] for i, j in pairs]))
        dist = float(np.mean([D[i, j] for i, j in pairs]))
        pred = float(np.mean([predict(D[i, j]) for i, j in pairs]))

        # Null: random farm sets of the same size, same statistic.
        null = []
        for _ in range(DRAWS):
            s = RNG.choice(len(names), size=len(m), replace=False)
            s = sorted(s)
            p = [(i, j) for a, i in enumerate(s) for j in s[a + 1:]]
            null.append(np.mean([Corr[i, j] for i, j in p]))
        null = np.array(null)
        rank = int((null < obs).sum())
        out.append({
            "group_id": g, "n_farms": len(m),
            "mean_distance_km": round(dist, 1),
            "observed_corr": round(obs, 4),
            "predicted_from_distance": round(pred, 4),
            "residual": round(obs - pred, 4),
            "null_mean_corr": round(float(null.mean()), 4),
            "p_vs_random_farms": round((rank + 1) / (DRAWS + 1), 4),
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    print(f"{'group':<12}{'n':>3}{'dist km':>9}{'observed':>10}{'from dist':>11}{'resid':>8}{'vs random':>11}")
    for r in out:
        print(f"{r['group_id']:<12}{r['n_farms']:>3}{r['mean_distance_km']:>9.1f}"
              f"{r['observed_corr']:>10.3f}{r['predicted_from_distance']:>11.3f}"
              f"{r['residual']:>+8.3f}{r['p_vs_random_farms']:>11.3f}")

    res = np.array([r["residual"] for r in out])
    print(f"\nmean residual across {len(out)} groups: {res.mean():+.4f}")
    print(f"groups beating the distance-only prediction: {(res > 0).sum()} of {len(out)}")
    print("\nReading this: a residual near zero means the group's wind correlation is")
    print("fully explained by how close its farms are. The grouping would then carry")
    print("no weather information beyond proximity, which is what EirGrid claim --")
    print("they group on NETWORK EFFECTIVENESS, not on weather.")
    print(f"\nwrote {OUT.name}")
    return out


if __name__ == "__main__":
    main()
