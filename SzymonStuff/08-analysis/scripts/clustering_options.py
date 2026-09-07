"""
Three ways to reconstruct EirGrid's constraint groups, scored side by side.

NO CHOICE IS MADE HERE. Decisions D1 (overlapping or disjoint) and D2 (scoring
metric) are the user's, and this script exists to make them with evidence rather
than in the abstract. It runs all three candidate methods on the same
effectiveness data and scores each by every candidate metric.

THE STRUCTURAL PROBLEM. EirGrid's groups OVERLAP - a farm can belong to several
at once, and in this data farms carry up to four tags. Standard clustering
(k-means, spectral) produces a DISJOINT, EXHAUSTIVE partition: every farm in
exactly one cluster. So the usual tool cannot produce the shape of the answer,
which is why two of the three methods below are overlapping ones.

THE THREE METHODS

  1. THRESHOLD    For each transmission line, take every farm whose effectiveness
                  on that line exceeds a cutoff. Each line yields a candidate
                  group; identical member sets are merged. Overlap arises
                  naturally because a farm can clear the bar on several lines.
                  This is closest to EirGrid's own words - they group farms "by
                  their effectiveness to alleviate constraints", one constraint
                  at a time.

  2. FUZZY C-MEANS  Every farm gets a membership weight in every cluster; a farm
                  belongs to each cluster where its weight exceeds a cutoff.
                  Overlapping, but the clusters are found in feature space
                  rather than per-constraint. Implemented directly (20 lines) to
                  avoid adding a dependency.

  3. SPECTRAL     The workshop method: eigenvectors of the similarity graph, then
                  k-means. DISJOINT, so it cannot reproduce overlap. Included as
                  the honest baseline - if it scores close to the others, the
                  overlap machinery is not earning its place.

THE THREE METRICS

  omega index     Agreement on how many groups each PAIR of farms shares,
                  corrected for chance. The standard measure for overlapping
                  clusterings, and the closest analogue to ARI.
  best-match F1   Each true group matched to its best-fitting predicted cluster;
                  F1 averaged both directions. Easy to explain to a judge.
  precision/recall  Per-group detail behind the F1, so a specific group can be
                  inspected rather than trusting a single number.

ARI and NMI are deliberately absent: they assume disjoint partitions and are not
valid here.

Output: clustering-options-scores.csv, clustering-options-per-group.csv
"""
import csv
import sys
import warnings
from pathlib import Path
from itertools import combinations

FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
OUT_DIR = FOLDER / "script-output"

import numpy as np
import pandas as pd
from sklearn.cluster import SpectralClustering

warnings.filterwarnings("ignore")
import pypsa

NET = ROOT / "03-network" / "script-output" / "ireland-network.nc"
MAP = ROOT / "03-network" / "script-output" / "farm-to-constraint-group-map.csv"
OUT_SCORES = OUT_DIR / "clustering-options-scores.csv"
OUT_GROUPS = OUT_DIR / "clustering-options-per-group.csv"

RNG = np.random.default_rng(0)


# ---------------------------------------------------------------- metrics

def omega_index(truth, pred, n):
    """Agreement on the number of clusters each pair shares, chance-corrected."""
    pairs = list(combinations(range(n), 2))
    t = np.array([len(truth[i] & truth[j]) for i, j in pairs])
    p = np.array([len(pred[i] & pred[j]) for i, j in pairs])
    obs = float((t == p).mean())
    levels = set(t) | set(p)
    exp = sum((t == j).mean() * (p == j).mean() for j in levels)
    return (obs - exp) / (1 - exp) if exp < 1 else 0.0


def f1(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    prec, rec = inter / len(b), inter / len(a)
    return 2 * prec * rec / (prec + rec)


def best_match_f1(true_sets, pred_sets):
    """Average of: each true group's best F1, and each predicted cluster's best."""
    if not pred_sets or not true_sets:
        return 0.0, [], 0.0
    fwd = [max(f1(t, p) for p in pred_sets) for t in true_sets]
    rev = [max(f1(t, p) for t in true_sets) for p in pred_sets]
    return (np.mean(fwd) + np.mean(rev)) / 2, fwd, float(np.mean(rev))


def to_sets(labels_per_farm, n):
    return [set(labels_per_farm[i]) for i in range(n)]


# ---------------------------------------------------------------- methods

def method_threshold(A, cut=0.10):
    """One candidate group per line: every farm above the cutoff there."""
    groups, seen = [], set()
    for row in A.T:                                   # A is farms x lines
        members = frozenset(np.nonzero(np.abs(row) >= cut)[0].tolist())
        if len(members) >= 2 and members not in seen:
            seen.add(members)
            groups.append(set(members))
    return groups


def fuzzy_cmeans(A, k, m=2.0, iters=150, tol=1e-6):
    """Standard FCM. Returns the membership matrix, farms x k."""
    n = A.shape[0]
    U = RNG.random((n, k))
    U /= U.sum(axis=1, keepdims=True)
    for _ in range(iters):
        Um = U ** m
        centres = (Um.T @ A) / Um.sum(axis=0)[:, None]
        d = np.linalg.norm(A[:, None, :] - centres[None, :, :], axis=2)
        d = np.fmax(d, 1e-12)
        inv = d ** (-2 / (m - 1))
        U_new = inv / inv.sum(axis=1, keepdims=True)
        if np.abs(U_new - U).max() < tol:
            U = U_new
            break
        U = U_new
    return U


def method_fuzzy(A, k, cut_mult=2.0, U=None):
    """A farm joins a cluster where its membership exceeds cut_mult / k.

    The cutoff must scale with k: memberships sum to 1 across k clusters, so a
    fixed 0.25 is unreachable once k is large and every cluster comes back empty.
    A multiple of the uniform level 1/k is the meaningful comparison.
    """
    if U is None:
        U = fuzzy_cmeans(A, k)
    cut = cut_mult / k
    return [set(np.nonzero(U[:, c] >= cut)[0].tolist()) for c in range(k)]


def method_spectral(A, k):
    sim = np.corrcoef(A)
    sim = np.nan_to_num((sim + 1) / 2)                # map to [0, 1]
    labels = SpectralClustering(n_clusters=k, affinity="precomputed",
                                random_state=0, assign_labels="kmeans").fit_predict(sim)
    return [set(np.nonzero(labels == c)[0].tolist()) for c in range(k)]


# ---------------------------------------------------------------- main

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    n = pypsa.Network(str(NET))
    n.determine_network_topology()
    sub = n.sub_networks.obj[n.buses.sub_network.value_counts().index[0]]
    sub.calculate_PTDF()
    names = sub.branches_i().get_level_values(1).to_numpy()
    PTDF = pd.DataFrame(sub.PTDF, index=names,
                        columns=sub.components.buses.static.index)

    farms = pd.read_csv(MAP)
    farms = farms[(farms.matched == "yes") & farms.model_bus.isin(PTDF.columns)]
    farms = farms.reset_index(drop=True)
    Pw = PTDF[farms.model_bus.values].to_numpy()
    cap = farms.mec_mw.fillna(0).to_numpy(float)
    w = cap / cap.sum() if cap.sum() else np.full(len(cap), 1 / len(cap))
    A = (Pw - (Pw @ w)[:, None]).T                    # farms x lines, fleet-relative
    nf = A.shape[0]

    # Ground truth: farm -> set of real group ids (nationwide group excluded).
    truth_per_farm, all_groups = [], {}
    for i, row in farms.iterrows():
        gs = {g for g in str(row.groups_via_model or "").split(";") if g and g != "ROI/1"}
        truth_per_farm.append(gs)
        for g in gs:
            all_groups.setdefault(g, set()).add(i)
    true_sets = [s for s in all_groups.values() if len(s) >= 2]
    k = len(true_sets)
    print(f"farms {nf}, real groups with 2+ members {k}")
    overlap = np.mean([len(s) for s in truth_per_farm])
    print(f"average real group memberships per farm: {overlap:.2f} "
          f"(so the answer genuinely overlaps)\n")

    # Calibrate each overlapping method so it produces roughly the same amount
    # of overlap as the real answer. Comparing methods at arbitrary cutoffs is
    # not a fair test - each should be shown at its own best setting.
    def memberships_per_farm(pred_sets):
        c = np.zeros(nf)
        for st in pred_sets:
            for i in st:
                c[i] += 1
        return c.mean()

    print("calibrating cutoffs so overlap matches the real 1.88 memberships/farm")
    thr_grid = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60]
    thr_best, thr_gap = 0.30, 1e9
    for c in thr_grid:
        mpf = memberships_per_farm(method_threshold(A, c))
        if abs(mpf - overlap) < thr_gap:
            thr_best, thr_gap = c, abs(mpf - overlap)
        print(f"   threshold {c:.2f} -> {mpf:5.2f} memberships/farm")
    print(f"   chosen: {thr_best:.2f}")
    print()

    U = fuzzy_cmeans(A, k)
    # Memberships collapse sharply between 1.0/k and 1.5/k, so the grid is
    # fine there; a coarse grid lands on an empty clustering.
    fcm_grid = [0.5, 0.8, 1.0, 1.1, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5]
    fcm_best, fcm_gap = 1.0, 1e9
    for c in fcm_grid:
        mpf = memberships_per_farm(method_fuzzy(A, k, c, U))
        # An empty clustering is never a valid calibration, however close its
        # membership count happens to look.
        if mpf > 0 and abs(mpf - overlap) < fcm_gap:
            fcm_best, fcm_gap = c, abs(mpf - overlap)
        print(f"   fuzzy cutoff {c:.1f}/k -> {mpf:5.2f} memberships/farm")
    print(f"   chosen: {fcm_best:.1f}/k")
    print()

    methods = {
        f"1 threshold >= {thr_best:.2f} (overlapping)": method_threshold(A, thr_best),
        f"2 fuzzy c-means {fcm_best:.1f}/k (overlapping)": method_fuzzy(A, k, fcm_best, U),
        "3 spectral (disjoint)": method_spectral(A, k),
    }

    scores, per_group = [], []
    for label, pred_sets in methods.items():
        pred_per_farm = [set() for _ in range(nf)]
        for ci, s in enumerate(pred_sets):
            for i in s:
                pred_per_farm[i].add(ci)
        om = omega_index(truth_per_farm, pred_per_farm, nf)
        bm, fwd, rev = best_match_f1(true_sets, [s for s in pred_sets if s])
        sizes = [len(s) for s in pred_sets if s]
        mem = np.mean([len(s) for s in pred_per_farm])
        scores.append({
            "method": label,
            "n_clusters": len(sizes),
            "median_cluster_size": int(np.median(sizes)) if sizes else 0,
            "avg_memberships_per_farm": round(float(mem), 2),
            "omega_index": round(om, 4),
            "best_match_f1": round(float(bm), 4),
            "recall_side_f1": round(rev, 4),
        })
        for gname, fwd_score in zip([g for g, s in all_groups.items() if len(s) >= 2], fwd):
            per_group.append({"method": label, "group_id": gname,
                              "n_true_members": len(all_groups[gname]),
                              "best_f1": round(float(fwd_score), 4)})

    with open(OUT_SCORES, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(scores[0]))
        wr.writeheader()
        wr.writerows(scores)
    with open(OUT_GROUPS, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(per_group[0]))
        wr.writeheader()
        wr.writerows(per_group)

    print(f"{'method':<32}{'clusters':>9}{'memb/farm':>11}{'omega':>9}{'F1':>8}")
    for s in scores:
        print(f"{s['method']:<32}{s['n_clusters']:>9}"
              f"{s['avg_memberships_per_farm']:>11.2f}"
              f"{s['omega_index']:>9.3f}{s['best_match_f1']:>8.3f}")
    print(f"\n{'(real answer)':<32}{k:>9}{overlap:>11.2f}{1.0:>9.3f}{1.0:>8.3f}")

    print("\nHow to read this")
    print("  omega  agreement on how many groups each PAIR shares, chance-corrected.")
    print("         0 = no better than chance, 1 = perfect.")
    print("  F1     how well each real group is matched by some predicted cluster.")
    print(f"  memb/farm is calibrated to the real {overlap:.2f}, so methods are")
    print("         compared at a like-for-like amount of overlap.")
    print("\nDECISIONS D1 AND D2 REMAIN OPEN. This is evidence, not a choice.")
    print(f"\nwrote {OUT_SCORES.name}, {OUT_GROUPS.name}")
    return scores


if __name__ == "__main__":
    main()
