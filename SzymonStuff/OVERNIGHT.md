# Overnight Work — 5/6 September 2026

**Everything added while you were asleep, in one place.**

Nothing existing was modified, moved, renamed or deleted. Every item below is
**new** and sits alongside the work that was already there. If you deleted this
whole list, yesterday's repository would be exactly as you left it.

**Read time: 5 minutes. Then one decision, and you're building.**

---

## The short version

| | |
|---|---|
| ✅ **N-1 works and is verified** | BODF hand-checked 5/5, including the radial-line edge case |
| ✅ **N-1 triples the coupling map** | 7,041 → 24,887 meaningful farm-line pairs (+253%) |
| ✅ **Critical outages ranked** | Which single line trips put the most wind at risk |
| ⚠️ **N-1 does NOT improve grouping** | And I chased down why — it was my method, not the grid |
| ⚠️ **No clustering method reconstructs the groups yet** | All three score omega ≈ 0. This is the honest headline |
| 🔓 **D1 and D2 still open** | As instructed. Evidence gathered, no choice made |

**The one thing to understand before you start:** yesterday's result — that groups
are electrically coherent — still stands and is unaffected. But *coherent* and
*reconstructable* turn out to be different things, and that gap is now measured.
See [§4](#4-the-honest-headline).

---

## 1. What was added

### New scripts (6)

| File | Purpose |
|---|---|
| [03-network/scripts/verify_bodf.py](03-network/scripts/verify_bodf.py) | Hand-verifies N-1 outage factors. **5/5 pass** |
| [03-network/scripts/compute_n1_effectiveness.py](03-network/scripts/compute_n1_effectiveness.py) | Contingency-aware effectiveness, plus the critical-outage ranking |
| [08-analysis/scripts/groups_vs_n1_effectiveness.py](08-analysis/scripts/groups_vs_n1_effectiveness.py) | Re-runs the coherence test on N-1 |
| [08-analysis/scripts/n1_feature_comparison.py](08-analysis/scripts/n1_feature_comparison.py) | Three ways of building an N-1 feature, compared |
| [08-analysis/scripts/clustering_options.py](08-analysis/scripts/clustering_options.py) | **The three clustering methods, scored** |
| *(figure 14 added to the existing make_figures.py)* | Clustering comparison chart |

### New outputs (9)

| File | Contents |
|---|---|
| `03-network/script-output/effectiveness-n1-farm-by-line.csv` | 24,887 worst-case pairs, each naming the outage that causes it |
| `03-network/script-output/critical-contingencies.csv` | Outages ranked by wind capacity at risk |
| `03-network/script-output/effectiveness-n1-matrix.npy` + `-order.csv` | The full N-1 matrix |
| `08-analysis/script-output/groups-vs-n1-effectiveness-test.csv` | N-1 coherence result |
| `08-analysis/script-output/n1-feature-comparison.csv` | A / B / C feature comparison |
| `08-analysis/script-output/clustering-options-scores.csv` | The three methods scored |
| `08-analysis/script-output/clustering-options-per-group.csv` | Per-group detail behind the scores |
| `07-figures/charts/14-clustering-options.png` | The comparison chart |

### Nothing else touched

Existing scripts were re-run (they are reproducible, so outputs regenerate
identically). No file was renamed, moved or deleted. No folder structure changed.

---

## 2. N-1 works, and it was worth doing

**Verification first, as with PTDF.** Three lines in a triangle: outage one and
its flow must travel the only other route, so the whole flow lands on the other
two lines with a sign flip on the one it runs against. Plus a radial-line case,
where outaging the only connection to a bus splits the network and the answer
must be *undefined* rather than a plausible-looking number.

**5 of 5 pass.** ([verify_bodf.py](03-network/scripts/verify_bodf.py))

**On the real network:**

| | |
|---|---|
| Contingencies usable | **714 of 770** |
| Radial / network-splitting, excluded | 56 |
| Farm-line pairs above threshold, base case | 7,041 |
| Farm-line pairs above threshold, under N-1 | **24,887 (+253%)** |

**Base-case analysis understates the problem by a factor of three.** Most farms
that matter for a line only matter *after* something else trips — which is
exactly why EirGrid define effectiveness against contingency conditions.

### The critical outages

Ranked by distinct wind capacity affected (no double-counting):

| Outage | Rating | Lines affected | Wind MW |
|---|---|---|---|
| `DFR(I)(T)>DFR(I)(Z)_110L1` | 99 | 22 | 3,195 |
| `LOU(I)(Z)>WOO(I)(Z)_220L1` | 350 | 31 | 3,156 |
| `CSH(I)(Z)>CLN(I)(Z)_110L1` | 178 | 10 | 3,116 |
| `BLC(I)(Z)>GRA(I)(Z)_110L1` | 140 | 2 | 3,038 |
| `CLO(I)(Z)>GOL(I)(T)_110L1` | 187 | 19 | 3,036 |

Full list in `critical-contingencies.csv`. **This is presentable on its own:**
*"these ten single-line outages drive Irish wind constraint."*

---

## 3. N-1 does not improve grouping — and I found out why

The straightforward N-1 test **failed**, and I want you to see the whole chain
rather than just the conclusion.

**First result:** worst-case N-1 effectiveness explained the groups *worse* — 5
of 12 groups beat the null instead of 11, mean excess −0.124 instead of +0.384.
Every single group got worse.

**That could mean two very different things**, so I tested which:

- *the grid* — N-1 genuinely isn't how groups are defined, or
- *my method* — "worst case over 714 outages" takes, for each farm and line, the
  maximum over **different** outages. Two farms in the same group may peak under
  different contingencies, so their vectors describe different physical
  scenarios and are not comparable. A maximum also keeps one number and throws
  away 713.

**So I built a fairer N-1 feature:** evaluate every farm under the **same** fixed
set of contingencies (base case plus the top 20) and stack the results.

| Feature | Beats null | Mean excess |
|---|---|---|
| A — base case | 11/12 | **+0.384** |
| B — worst case over N-1 | 5/12 | −0.124 |
| C — base + top 20 contingencies, same for all | 11/12 | **+0.383** |

**Verdict: it was my method, not the grid.** A properly-constructed N-1 feature
matches the base case almost exactly (+0.383 vs +0.384).

**What this means practically.** N-1 adds no *grouping* information the base case
did not already carry — but it destroys none either, and it remains essential for
identifying *which lines and outages are at risk* (§2). Those are two different
questions. **For clustering, use base-case effectiveness. It is simpler and just
as good.** That is a real simplification, established rather than assumed.

---

## 4. The honest headline

**No clustering method reconstructs EirGrid's groups yet.**

All three were calibrated to produce the same amount of overlap as the real
answer (1.88 group memberships per farm), so the comparison is like-for-like.

| Method | Clusters | Memb/farm | Omega | Best-match F1 |
|---|---|---|---|---|
| 1 Threshold ≥ 0.30 (overlapping) | 48 | 1.77 | **−0.001** | **0.583** |
| 2 Fuzzy c-means (overlapping) | 20 | 9.15 | −0.039 | 0.383 |
| 3 Spectral (disjoint) | 20 | 1.00 | −0.011 | 0.530 |
| *(the real answer)* | *20* | *1.88* | *1.000* | *1.000* |

**Read the two metrics separately — they say different things:**

- **F1 ≈ 0.58** — individual real groups *are* matched moderately well by some
  predicted cluster. Not nothing.
- **Omega ≈ 0** — the *pairwise overlap structure* is not reproduced at all.
  Which farms share how many groups is no better than chance.

### Why this matters, and why it is not a setback

Yesterday's finding was that real groups **are internally coherent** in
effectiveness: 11 of 12 beat a random null. That stands, untouched.

But coherence and reconstructability are different claims:

> *Members of a real group resemble each other* ✅ **proven**
> *Clustering on effectiveness recovers the real groups* ❌ **not yet**

**The likely reason, and the lead worth following.** We cluster across **all 770
branches**, but EirGrid define each group against **one specific overload on one
specific circuit**. Averaging over every branch dilutes exactly the signal that
defines a group. Threshold scores best of the three, and it is the only method
that works one constraint at a time — which is suggestive.

**The obvious next experiment:** restrict the effectiveness vectors to the ~40
circuits the WDT document actually names, instead of all 770. You already have
that list in `constraint-groups-to-stations.csv`. If the score jumps, that is
your result and it explains itself in one sentence.

I did not run it — it edges toward choosing an approach, which is D1's territory.

---

## 5. Your decisions, unchanged and now informed

**Both remain open, exactly as instructed. No choice was made.**

**D1 — overlapping or disjoint?** Evidence: threshold (overlapping) scores best
on both metrics, and it is closest to EirGrid's own wording. Spectral (disjoint)
is not far behind on F1 despite structurally being unable to represent overlap —
so the overlap machinery is not yet earning its keep. *Ten minutes with the
table above and figure 14.*

**D2 — which metric?** Now concrete rather than abstract. F1 and omega
**disagree**, and that disagreement is informative: F1 says "we find groups",
omega says "we don't find the structure". Choosing between them is choosing what
claim you want to make. ARI and NMI stay excluded — they assume disjoint
partitions and are invalid here.

---

## 6. Verification

Standard held throughout:

- BODF hand-verified 5/5 before anything was built on it
- All 24 scripts re-run clean from scratch
- Every relative link checked
- Two of my own bugs caught and fixed rather than shipped: **wind capacity was
  being double-counted** across lines in the contingency ranking (51,860 MW
  against a 3,201 MW fleet), and **fuzzy c-means produced zero clusters** because
  my membership cutoff was unreachable at k=20

---

## 7. When you sit down

1. **Read §4.** It changes what "success" looks like today.
2. **Make D1 and D2.** Ten minutes with the table and figure 14.
3. **Run the restricted-branch experiment** (§4). Highest-value, ~30 minutes,
   and it either lands or rules out a hypothesis cleanly.
4. **Then Stage 3** — DC-OPF and the euro figure. Solver installed and tested.

Full detail lives in the folder READMEs, as always. This file is the summary and
can be deleted once you have read it — nothing depends on it.
