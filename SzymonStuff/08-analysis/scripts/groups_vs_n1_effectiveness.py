"""
Does N-1 effectiveness explain EirGrid's groups better than the base case?

The base-case test (groups_vs_effectiveness.py) found 11 of 12 real constraint
groups more electrically coherent than random farm sets, mean excess +0.384.

But EirGrid define effectiveness against "the 'base case', 'N-1' or 'N-1-1'
overload" - contingency conditions included. So the fairer test uses worst-case
N-1 effectiveness. This runs the identical procedure on that richer feature and
reports whether it improves, matches, or does worse.

It may well not improve. Worst-case-over-contingencies is a maximum, and maxima
are noisier than the quantity they summarise; taking the largest of 714 numbers
can wash out the structure that made the base case coherent. That is a real
possibility and the result is reported either way.

Method, identical to the base-case test so the two are comparable:
    statistic   mean pairwise cosine similarity of members' effectiveness vectors
    null        500 random farm sets of the same size

Output: groups-vs-n1-effectiveness-test.csv
"""
import csv
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
OUT_DIR = FOLDER / "script-output"

import numpy as np
import pandas as pd

NET_OUT = ROOT / "03-network" / "script-output"
MATRIX = NET_OUT / "effectiveness-n1-matrix.npy"
ORDER = NET_OUT / "effectiveness-n1-order.csv"
MAP = NET_OUT / "farm-to-constraint-group-map.csv"
BASE = OUT_DIR / "groups-vs-effectiveness-test.csv"
OUT = OUT_DIR / "groups-vs-n1-effectiveness-test.csv"

RNG = np.random.default_rng(0)
DRAWS = 500


def cosine_mean(V, idx):
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

    rel = np.load(MATRIX)                       # lines x farms
    order = pd.read_csv(ORDER)
    farm_names = order[order.axis == "farm"].sort_values("index").name.tolist()
    A = rel.T                                   # farms x lines
    print(f"N-1 effectiveness vectors: {A.shape[0]} farms x {A.shape[1]} branches\n")

    farms = pd.read_csv(MAP)
    farms = farms[farms.matched == "yes"].set_index("farm")
    pos = {f: i for i, f in enumerate(farm_names)}

    members = {}
    for f in farm_names:
        if f not in farms.index:
            continue
        row = farms.loc[f]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        for g in str(row.groups_via_model or "").split(";"):
            if g and g != "ROI/1":
                members.setdefault(g, []).append(pos[f])

    out = []
    for g, idx in sorted(members.items()):
        if len(idx) < 4:
            continue
        obs = cosine_mean(A, idx)
        null = np.array([cosine_mean(A, RNG.choice(len(farm_names), len(idx), replace=False))
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
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    base = {r["group_id"]: r for r in csv.DictReader(open(BASE, encoding="utf-8"))}

    print(f"{'group':<12}{'n':>4}{'base excess':>13}{'N-1 excess':>12}{'change':>9}{'p (N-1)':>10}")
    for r in out:
        b = base.get(r["group_id"])
        be = float(b["excess"]) if b else float("nan")
        print(f"{r['group_id']:<12}{r['n_farms']:>4}{be:>13.3f}{r['excess']:>12.3f}"
              f"{r['excess'] - be:>+9.3f}{r['p_vs_random_farms']:>10.3f}")

    n1 = np.array([r["excess"] for r in out])
    bs = np.array([float(base[r["group_id"]]["excess"]) for r in out if r["group_id"] in base])
    sig_n1 = sum(1 for r in out if r["p_vs_random_farms"] < 0.05)
    sig_b = sum(1 for r in out
                if r["group_id"] in base and float(base[r["group_id"]]["p_vs_random_farms"]) < 0.05)

    print(f"\n{'':<26}{'base case':>12}{'N-1':>10}")
    print(f"{'groups beating the null':<26}{sig_b:>9} /{len(out):<2}{sig_n1:>7} /{len(out):<2}")
    print(f"{'mean excess similarity':<26}{bs.mean():>12.3f}{n1.mean():>10.3f}")

    better = int((n1 > bs).sum())
    print(f"\ngroups more coherent under N-1 than base case: {better} of {len(out)}")
    if n1.mean() > bs.mean():
        print("VERDICT: N-1 effectiveness explains the grouping BETTER.")
    elif abs(n1.mean() - bs.mean()) < 0.02:
        print("VERDICT: no material difference. The base case already captures it.")
    else:
        print("VERDICT: N-1 explains the grouping WORSE than the base case.")
        print("Worst-case-over-contingencies is a maximum, and maxima are noisy;")
        print("that is the likely cause. Report it as measured - the base-case")
        print("result stands on its own and does not need this one to succeed.")
    print(f"\nwrote {OUT.name}")
    return out


if __name__ == "__main__":
    main()
