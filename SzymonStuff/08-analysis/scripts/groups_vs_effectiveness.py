"""
Do EirGrid's real constraint groups contain farms with similar effectiveness?

This is the test the whole project rests on. EirGrid say they group farms by
electrical effectiveness. We can now compute effectiveness directly. So:

    take a real constraint group, and ask whether its members are more alike -
    in their effectiveness across all 770 branches - than an arbitrary set of
    farms of the same size.

If yes, EirGrid's stated method is confirmed from the outside, and clustering on
effectiveness is a sound way to reconstruct the groups. If no, either the model
is wrong or the grouping follows something other than topology.

The method mirrors the Session 2 workshop capstone: measure a statistic across a
partition, then compare it against a null that holds size fixed and varies only
the thing being tested.

    statistic   mean pairwise cosine similarity of members' effectiveness
                vectors (one vector per farm, 770 branches long)
    null        500 random farm sets of the same size

Compare against groups_vs_weather.py, which ran the same test using WEATHER and
found groups carry no information beyond proximity. If effectiveness succeeds
where weather failed, that is the case for the network approach made directly.

Output: groups-vs-effectiveness-test.csv
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

NET = ROOT / "03-network" / "script-output" / "ireland-network.nc"
MAP = ROOT / "03-network" / "script-output" / "farm-to-constraint-group-map.csv"
OUT = OUT_DIR / "groups-vs-effectiveness-test.csv"

RNG = np.random.default_rng(0)
DRAWS = 500


def cosine_mean(V, idx):
    """Mean pairwise cosine similarity among the rows in `idx`."""
    A = V[idx]
    norms = np.linalg.norm(A, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    A = A / norms
    S = A @ A.T
    iu = np.triu_indices(len(idx), k=1)
    return float(S[iu].mean()) if len(iu[0]) else np.nan


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    n = pypsa.Network(str(NET))
    n.determine_network_topology()
    sub = n.sub_networks.obj[n.buses.sub_network.value_counts().index[0]]
    sub.calculate_PTDF()
    buses = sub.components.buses.static.index
    P = pd.DataFrame(sub.PTDF, columns=buses)

    farms = pd.read_csv(MAP)
    farms = farms[(farms.matched == "yes") & farms.model_bus.isin(P.columns)]
    farms = farms.reset_index(drop=True)

    # One effectiveness vector per farm, fleet-relative so the slack cancels.
    A = P[farms.model_bus.values].to_numpy().T          # farms x branches
    cap = farms.mec_mw.fillna(0).to_numpy(float)
    w = cap / cap.sum() if cap.sum() else np.full(len(cap), 1 / len(cap))
    A = A - (w @ A)[None, :]
    print(f"effectiveness vectors: {A.shape[0]} farms x {A.shape[1]} branches\n")

    members = {}
    for i, row in farms.iterrows():
        for g in str(row.groups_via_model or "").split(";"):
            if g and g != "ROI/1":       # nationwide group is not a locality
                members.setdefault(g, []).append(i)

    out = []
    for g, idx in sorted(members.items()):
        if len(idx) < 4:
            continue
        obs = cosine_mean(A, idx)
        null = np.array([cosine_mean(A, RNG.choice(len(farms), len(idx), replace=False))
                         for _ in range(DRAWS)])
        rank = int((null < obs).sum())
        out.append({
            "group_id": g,
            "n_farms": len(idx),
            "observed_similarity": round(obs, 4),
            "null_mean_similarity": round(float(null.mean()), 4),
            "excess": round(obs - float(null.mean()), 4),
            "p_vs_random_farms": round((DRAWS - rank) / (DRAWS + 1), 4),
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w_ = csv.DictWriter(f, fieldnames=list(out[0]))
        w_.writeheader()
        w_.writerows(out)

    print(f"{'group':<12}{'n':>4}{'observed':>11}{'random':>10}{'excess':>9}{'p':>8}")
    for r in out:
        print(f"{r['group_id']:<12}{r['n_farms']:>4}{r['observed_similarity']:>11.3f}"
              f"{r['null_mean_similarity']:>10.3f}{r['excess']:>+9.3f}"
              f"{r['p_vs_random_farms']:>8.3f}")

    ex = np.array([r["excess"] for r in out])
    sig = sum(1 for r in out if r["p_vs_random_farms"] < 0.05)
    print(f"\ngroups tested                    : {len(out)}")
    print(f"more alike than random (p < 0.05): {sig} of {len(out)}")
    print(f"mean excess similarity           : {ex.mean():+.3f}")
    print("\nCompare groups-vs-weather-test.csv, where the same test on WEATHER")
    print("found no information beyond proximity. Effectiveness is the signal")
    print("the grouping actually encodes.")
    print(f"\nwrote {OUT.name}")
    return out


if __name__ == "__main__":
    main()
