# 05 — Workshops

Workshop material from the TPSA pre-hackathon week: graph theory and MCMC.
These are the techniques the project is built from.

**Layout.** `graph-theory/` the two notebooks · `mcmc/` slides, code and output

---

## Why the graph workshops matter

The worked example throughout is 162 Dublin electoral divisions with a census
attribute. That looks unrelated to the grid — it isn't. **The DC power flow is
the same matrix.**

The Laplacian `L = D − A` has the quadratic form `xᵀLx = Σ(xᵢ − xⱼ)²`: a sum of
squared differences across every edge, exactly like a chain of springs. On the
grid, bus voltage angles play the role of displacements, and power flow on a line
is the angle difference divided by the reactance. So:

| Workshop concept | Grid meaning |
|---|---|
| Laplacian `L = D − A` | The DC power flow matrix (susceptance-weighted) |
| Incidence matrix `B`, `BᵀB = L` | Branch–bus incidence; `Bθ` gives line flows directly |
| `λ₂`, algebraic connectivity | How hard the network is to cut |
| The barbell example | Ireland *is* a barbell: windy weak-network west, demand in Dublin, narrow waist between |
| RatioCut vs Ncut | Stops your clustering "discovering" one isolated wind farm |
| Choosing σ for edge weights | Your grouping depends on weighting, and you must show you checked |

**The one gap to close first.** The workshops teach the **unweighted** Laplacian.
The DC power flow needs the **susceptance-weighted** one,
`B = Aᵀ diag(1/x) A`, and line-flow sensitivity (PTDF) is a specific matrix
product involving a pseudo-inverse and a slack bus. That bridge is written down
nowhere in this repository yet. See [../01-brief/TODO.md](../01-brief/TODO.md) §2.

---

## Files, most important first

### 1. [graph-theory/GraphBasedComputationalTechniquesSession1.ipynb](graph-theory/GraphBasedComputationalTechniquesSession1.ipynb)
59 cells, eight sections:

| § | Topic |
|---|---|
| 1–2 | Data; eigenvector refresher on a spring chain |
| 3 | **Laplacian, incidence matrix, λ₂, the Fiedler vector** |
| 4 | **Spectral clustering; RatioCut vs Ncut** |
| 5 | Community detection (Louvain, planted block model) |
| 6 | Geospatial: contiguity graphs, betweenness, Fiedler on a real map |
| 7 | **Weighted clustering and the sensitivity to σ** |
| 8 | **Braess's paradox** — working four-node Frank–Wolfe implementation |

Section 8 is organiser point 4, ready to run. Section 3 is the foundation of the
whole project.

### 2. [graph-theory/GraphBasedComputationalTechniquesSession2.ipynb](graph-theory/GraphBasedComputationalTechniquesSession2.ipynb)
33 cells:

| § | Topic |
|---|---|
| 2 | **Moran's I** — is a spatial pattern real, or would random data look like this? |
| 3 | Diffusion on graphs, `u' = −Lu`, solved exactly by eigendecomposition |
| 4 | **The capstone** |

**The capstone is the most valuable single thing in either notebook, and it is
unfinished.** Cell 29 has step 1 only (`t = 0.2 #lambda2 = 5 vibes based`);
steps 2, 3, 4 and the conclusion are blank.

Its structure is the validation method for the entire project: **take a
partition, measure a physical quantity across it, then test that measurement
against a null of arbitrary but *plausible* partitions.** The important function
is `random_contiguous_partition()` — comparing against scattered random labels is
easy and proves nothing, whereas comparing against a *connected* region of the
same size is a fair fight.

Note `τ = 1/λ₂ = 16.4` for this graph, so times must be quoted as multiples of τ
rather than picked in absolute terms.

### 3. [mcmc/MCMCworkshop.py](mcmc/MCMCworkshop.py) — Potts model, Metropolis
A q-state Potts model on a 2D square lattice with single-site Metropolis updates.
Clean, well-commented, correct in its mechanics.

> ### ⚠️ Two problems before this is useful
>
> **1. There is a bug in the critical temperature.** The file has
> `beta_c = (1/J) * (1 + sqrt(q))`. The 2D Potts critical point is
> **`beta_c = ln(1 + √q) / J`** — the logarithm is missing. It follows from
> self-duality: `e^{βJ} − 1 = √q`.
>
> With q = 3 the true `β_c ≈ 1.005`, but the script runs at `β = 4.098` —
> **4.1× above critical.** [mcmc/potts_metropolis.csv](mcmc/potts_metropolis.csv) confirms
> it: the last 500 sweeps sit at `E = −200.00` exactly and `M = 1.000`, which is
> the frozen ground state of a 10×10 lattice (200 bonds). The run contains 2,000
> sweeps of a completely dead system.
>
> **2. There is no mapping to this problem.** Nowhere is it stated what a spin
> is, what the graph is, or what the Hamiltonian would be for the grid. COTHROM
> is cited as inspiration but the analogy is not written down.
>
> Only single-site Metropolis is implemented — the slowest algorithm. The Friday
> workshop covers cluster algorithms (Swendsen–Wang, Wolff) and replica exchange,
> which are what a partitioning problem would actually need.

### 4. [mcmc/MCMCworkshopSlides.pdf](mcmc/MCMCworkshopSlides.pdf) — the MCMC lecture
30 slides, David Lawton, 4 September 2026. Covers Monte Carlo integration,
Markov chains, the MCMC algorithm for statistical physics, the Potts model, and
frustrated systems. This is the theory behind `mcmc/MCMCworkshop.py`, and its
frustrated-systems section is the part relevant to a partitioning problem.

### 5. [mcmc/potts_metropolis.csv](mcmc/potts_metropolis.csv)
Output of the above: 2,000 sweeps, columns `sweep, E, M`. Useful only as evidence
of the frozen-system bug.

---

## An honest question about MCMC

If the task is clustering farms by their effectiveness vectors, **spectral
clustering plus k-means is deterministic, fast, and sufficient** — MCMC adds
nothing.

MCMC earns its place only if you write a *partition objective* with constraints
that have no closed form: contiguity, group-size limits, or overlapping
membership. That is a real possibility here, because EirGrid's groups genuinely
do overlap. But it should be a deliberate decision, not a drift into using the
technique because there was a workshop on it.

---

## References

| File | Source |
|---|---|
| `graph-theory/GraphBasedComputationalTechniquesSession1.ipynb` | TPSA workshop, "Graph-Based Computational Techniques", Tue 1 Sep 2026, SNIAM computer room, TCD. Source repo `github.com/farrencc/graph-methods` |
| `graph-theory/GraphBasedComputationalTechniquesSession2.ipynb` | Same workshop, session 2 |
| `mcmc/MCMCworkshop.py` | Written by Szymon Ablewicz for the TPSA "MCMC Methods" workshop, Fri 4 Sep 2026 (Potts model, spin glass, cluster algorithms, replica exchange) |
| `mcmc/MCMCworkshopSlides.pdf` | David Lawton, *Markov Chain Monte Carlo Methods: Random Numbers as a Tool for Physics Simulations*, TPSA workshop, 4 Sep 2026. 30 slides |
| `mcmc/potts_metropolis.csv` | **Generated** by `mcmc/MCMCworkshop.py` |

**Workshop series:** TPSA pre-hackathon workshops, 31 August – 4 September 2026,
Trinity College Dublin. Free, open to students from any university.

**Background reading:**
- Potts critical point via self-duality: R. B. Potts, "Some generalized
  order-disorder transformations," *Math. Proc. Camb. Phil. Soc.* **48** (1952)
  106–109. The square-lattice result is `β_c J = ln(1 + √q)`.
- Braess's paradox in power networks: D. Witthaut and M. Timme, *New Journal of
  Physics* **14** (2012) 083036, DOI
  [10.1088/1367-2630/14/8/083036](https://doi.org/10.1088/1367-2630/14/8/083036).
  Open access. Verified 5 Sep 2026.
- **COTHROM** — TPSA CLG's computational Irish electoral redistricting project,
  using Potts Hamiltonians, MCMC and simulated annealing on a graph-partitioning
  problem. Directly analogous machinery. <https://tpsa.ie/problem-solving>
