"""
Three ways to build an N-1 feature, compared fairly.

The first N-1 test (groups_vs_n1_effectiveness.py) found that worst-case
effectiveness explains EirGrid's groups WORSE than the base case: 5 of 12
groups beat the null instead of 11, mean excess -0.123 instead of +0.384.

Before accepting that as a fact about the grid, it is worth asking whether it is
a fact about the METHOD. Worst-case-over-contingencies takes, for each farm and
each line, the largest value over 714 different outages. Two farms in the same
group may hit their maximum under DIFFERENT outages, so their vectors describe
different physical scenarios and are not really comparable. The maximum is also
a noisy statistic: it keeps one number and discards 713.

A fairer N-1 feature evaluates every farm under the SAME set of contingencies
and stacks the results, so like is compared with like.

So this compares three features on the identical coherence test:

    A  base case              PTDF, intact network                    (reference)
    B  worst case over N-1    max over all valid outages              (noisy?)
    C  stacked fixed set      base case plus the top K contingencies,
                              all farms evaluated under the same ones

If C recovers what B lost, the earlier result was a methodological artefact and
should be reported as such. If C also fails, then base-case effectiveness really
is the better description of how EirGrid group farms, which is itself worth
knowing and worth saying.

Output: n1-feature-comparison.csv
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
CONT = ROOT / "03-network" / "script-output" / "critical-contingencies.csv"
OUT = OUT_DIR / "n1-feature-comparison.csv"

RNG = np.random.default_rng(0)
DRAWS = 500
TOP_K = 20          # how many contingencies to stack for feature C


def cosine_mean(V, idx):
    A = V[idx]
    norms = np.linalg.norm(A, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    A = A / norms
    S = A @ A.T
    iu = np.triu_indices(len(idx), k=1)
    return float(S[iu].mean()) if len(iu[0]) else np.nan


def score(A, members, label):
    """Run the coherence test on one feature matrix."""
    res = []
    for g, idx in sorted(members.items()):
        if len(idx) < 4:
            continue
        obs = cosine_mean(A, idx)
        null = np.array([cosine_mean(A, RNG.choice(A.shape[0], len(idx), replace=False))
                         for _ in range(DRAWS)])
        rank = int((null < obs).sum())
        res.append({"feature": label, "group_id": g, "n_farms": len(idx),
                    "observed": round(obs, 4),
                    "excess": round(obs - float(null.mean()), 4),
                    "p": round((DRAWS - rank) / (DRAWS + 1), 4)})
    return res


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
    valid = np.isfinite(BODF).all(axis=0)

    farms = pd.read_csv(MAP)
    farms = farms[(farms.matched == "yes") & farms.model_bus.isin(PTDF.columns)]
    farms = farms.reset_index(drop=True)
    Pw = PTDF[farms.model_bus.values].to_numpy()          # branches x farms
    cap = farms.mec_mw.fillna(0).to_numpy(float)
    w = cap / cap.sum() if cap.sum() else np.full(len(cap), 1 / len(cap))

    def relative(M):
        return M - (M @ w)[:, None]

    members = {}
    for i, row in farms.iterrows():
        for g in str(row.groups_via_model or "").split(";"):
            if g and g != "ROI/1":
                members.setdefault(g, []).append(i)

    # --- A: base case
    A_base = relative(Pw).T

    # --- B: worst case over all valid contingencies
    worst = Pw.copy()
    best = np.abs(Pw)
    for k in np.nonzero(valid)[0]:
        cand = Pw + np.outer(BODF[:, k], Pw[k, :])
        cand[k, :] = Pw[k, :]
        mag = np.abs(cand)
        better = mag > best
        if better.any():
            worst = np.where(better, cand, worst)
            best = np.where(better, mag, best)
    A_worst = relative(worst).T

    # --- C: base case stacked with the top K contingencies, same set for all farms
    top = pd.read_csv(CONT).contingency.head(TOP_K).tolist()
    idx_of = {s: i for i, s in enumerate(names)}
    blocks = [relative(Pw)]
    used = 0
    for c in top:
        k = idx_of.get(c)
        if k is None or not valid[k]:
            continue
        cand = Pw + np.outer(BODF[:, k], Pw[k, :])
        cand[k, :] = Pw[k, :]
        blocks.append(relative(cand))
        used += 1
    A_stack = np.vstack(blocks).T
    print(f"feature C stacks the base case plus {used} contingencies "
          f"-> {A_stack.shape[1]} dimensions per farm\n")

    rows = (score(A_base, members, "A base case")
            + score(A_worst, members, "B worst case over N-1")
            + score(A_stack, members, f"C base + top {used} contingencies"))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    print(f"{'feature':<34}{'beats null':>12}{'mean excess':>14}")
    summary = {}
    for label in dict.fromkeys(r["feature"] for r in rows):
        sub_r = [r for r in rows if r["feature"] == label]
        sig = sum(1 for r in sub_r if r["p"] < 0.05)
        mean = float(np.mean([r["excess"] for r in sub_r]))
        summary[label] = (sig, len(sub_r), mean)
        print(f"{label:<34}{sig:>7} /{len(sub_r):<3}{mean:>14.3f}")

    a = summary["A base case"]
    c = summary[f"C base + top {used} contingencies"]
    print()
    if c[2] > a[2] + 0.02:
        print("VERDICT: a fixed contingency set explains the grouping BETTER than")
        print("the base case. The earlier N-1 failure was the max, not the physics.")
    elif abs(c[2] - a[2]) <= 0.02:
        print("VERDICT: the fixed contingency set matches the base case. N-1 adds")
        print("no information the base case did not already carry, but nor does it")
        print("destroy any - so the earlier failure WAS an artefact of the maximum.")
    else:
        print("VERDICT: even a fixed contingency set does worse than the base case.")
        print("Base-case effectiveness is the better description of the grouping.")
    print(f"\nwrote {OUT.name}")
    return rows


if __name__ == "__main__":
    main()
