# TPSA Hackathon 2026 — Full Context Brief

**Compiled:** 29 August 2026 · **Revised:** 1 September 2026
**For:** Szymon Ablewicz (undergrad theoretical physics, TCD)
**Companion files:**
- [../02-curtailment/ireland-high-voltage-grid.md](../02-curtailment/ireland-high-voltage-grid.md) — the deep sourced briefing on constraint groups, dispatch machinery and current statistics. **Where this brief and that file disagree, that file wins.**
- [../06-reference/irish-grid-curtailment-data-sources.md](../06-reference/irish-grid-curtailment-data-sources.md) — the data/tooling catalogue (treat as a list of links, not a source of claims).

> **Provenance tags used throughout.** Sources here are of very mixed reliability, so every claim is tagged:
> `[EMAIL]` from the official TPSA announcement · `[ORGANISER]` verbal, from a PhD-student organiser/director · `[AI-UNVERIFIED]` from an LLM-generated list, may be wrong or hallucinated · `[VERIFIED 29-08-26]` / `[VERIFIED 01-09-26]` checked against a live source on that date · `[MINE]` inference or judgement, not a sourced fact.

> **Revision note, 1 September 2026.** Four things changed materially: the constraint-group count (§3.7), the origin of the 15–25% figure (§3.2), the cost figures (§4), and the licence status of the Irish network model — which turned out to be openly published and settled without needing to ask anyone (§5). The project angle in §6 has been rewritten as a result.

---

## 1. The event

| | |
|---|---|
| **Event** | TPSA Hackathon 2026 `[EMAIL]` |
| **Dates** | Mon 7 – Fri 11 September 2026 `[EMAIL]` |
| **Topic** | "Efficiency in Ireland's Electricity Grid" `[EMAIL]` |
| **Run by** | TPSA CLG. in conjunction with TPSA (student society) and **TF Wind** (Trinity Floating Wind) `[EMAIL]` |
| **Venue** | Space in the new **E3 Learning Foundry**, TCD — but teams may work anywhere, anytime `[EMAIL]` |
| **Teams** | Up to 5 people `[EMAIL]` |
| **Format** | Day 1: full problem briefing. Then self-directed work. **Friday: each group presents progress.** `[EMAIL]` |
| **Structure** | Problem broken into steps of increasing complexity, so beginners and experienced coders can both contribute `[EMAIL]` |
| **Contact** | Caoimhe Burke (she/her), TPSA Secretary 2025/26, tpsa@tcd.ie `[EMAIL]` |

### The stated brief `[EMAIL]`
> "You will be tasked with developing models and optimising decision making as they relate to Ireland's high voltage electrical infrastructure, **with the goal of reducing the amount of wind energy wasted every year**. You can utilise your knowledge of topics including electromagnetism, linear algebra and graph theory, as well as Python or other computational skills."

Details on location and topic are promised **before** the hackathon to those who signed up. `[EMAIL]`

### Why it's worth taking seriously `[EMAIL]`
Previous TPSA hackathons have led to: presentation at a conference, a funded PhD, and the COTHROM project (§7). Framed explicitly as career-boosting.

---

## 2. The workshops (31 Aug – 4 Sep, SNIAM computer room, TCD, 10:00–16:00) `[EMAIL]`

Optional, free, open to students from any university, sign-up required. Run by fellow students.

| Day | Topic | Relevance to the hackathon |
|---|---|---|
| Mon 31/08 | **Introduction to Python** (Saoirse) — variables, operators, flow control, dicts/sets/lists/tuples, arrays, functions, timing, OOP, numpy/matplotlib/pandas | Baseline |
| Tue 01/09 | **Graph-Based Computational Techniques** — graph Laplacian, **spectral clustering**, spatial autocorrelation statistics, geospatial network analysis, diffusion-type PDEs on graphs. Assumes linear algebra + NumPy | **Directly applicable.** The email explicitly flags this one for the hackathon |
| Wed 02/09 | Intro to Quantum Information and QuSpin — classical information theory, qubits, density operators, mixed vs pure states, entanglement, spin chains | Not relevant |
| Thu 03/09 | Topological Quantum Computation and Error Correction — topologically ordered phases, lattice of spins, energy spectrum and degeneracies | Not relevant |
| Fri 04/09 | **MCMC methods** — Potts model, spin glass, cluster algorithms, replica exchange | Possibly relevant: the PSA's COTHROM project used Potts + MCMC + simulated annealing on a graph-partitioning problem. Same machinery could apply to clustering or siting problems here |

### What the Tuesday workshop actually gave us `[VERIFIED 01-09-26]`

Two notebooks, saved in [../05-workshops/](../05-workshops/), source repo `github.com/farrencc/graph-methods`. The worked example throughout is 162 Dublin electoral divisions with a census attribute — but every technique in them maps onto the grid problem, and the code is reusable more or less as-is.

| Notebook section | What it teaches | How it maps onto the grid |
|---|---|---|
| S1 §2–3 — Laplacian, `L = D − A`, `xᵀLx = Σ(xᵢ−xⱼ)²` | The Laplacian is a spring chain: the quadratic form is the summed squared difference across every edge | The **DC power flow is the same matrix**. Bus voltage angles play the role of displacements, and power flow on a line is the angle difference over the reactance. Stage 1 of §6 is built on this |
| S1 §3 — incidence matrix `B`, `BᵀB = L` | `Bx` is the vector of differences across edges; orientation is bookkeeping that cancels | `B` is the branch–bus incidence matrix of the grid. `Bθ` gives you flows directly. This is the bridge from the workshop's toy graphs to a real network |
| S1 §3 — `λ₂`, algebraic connectivity, the Fiedler vector | One number for how hard a graph is to cut; the barbell example is a bottleneck made visible | Ireland's grid *is* a barbell: high-wind weak-network west, demand in Dublin, a narrow waist between. Constraint lives in the waist |
| S1 §4 — RatioCut vs Ncut, `eigh(L)` vs `eigh(L, D)` | Why the naive minimum cut isolates a single pendant node, and how normalisation fixes it | Prevents the failure mode where your clustering "discovers" one isolated wind farm |
| S1 §7 — weighted clustering, choosing σ | Turning an attribute into edge weights, and the sensitivity of the answer to that choice | The honest version of this problem: your grouping depends on how you weight edges, and you must show you checked. `λ₂ → 0` is the built-in warning that σ is too small and the graph has fallen apart |
| S1 §8 — Braess | Working four-node implementation with Frank–Wolfe user equilibrium | Organiser point 4, ready to run |
| S2 §2 — Moran's I | Is a spatial pattern real, or would random data look like this too? | Is curtailment geographically clustered, or does it just look that way? |
| S2 §3 — diffusion on graphs, `u' = −Lu` | Solved exactly by eigendecomposition; `τ = 1/λ₂` is the graph's natural timescale | The propagation-of-disturbance picture — and the same operator again |
| **S2 §4 — the capstone** | **Measure something across a proposed boundary, then compare it against randomly grown regions of the same size** | **The validation method for §6.** See below |

**The capstone is the most valuable single thing in either notebook**, and it is the part still unfinished. Its structure — take a partition, measure a physical quantity across it, then test that measurement against a null of arbitrary but *plausible* partitions — is exactly how you prove that a constraint grouping is real rather than an artefact of your algorithm. `random_contiguous_partition()` is the important function: comparing against scattered random labels is easy and proves nothing, whereas comparing against a connected region of the same size is a fair fight. Note also that its λ₂ = 0.0609 gives τ = 16.4, so times must be quoted as multiples of τ rather than picked in absolute terms.

---

## 3. Organiser guidance (verbal, from a PhD-student director) `[ORGANISER]`

1. **TF Wind** (Trinity Floating Wind) specialises in offshore wind farms, but this hackathon will be **mainly network optimisation and computational physics**, plus possibly using physics to improve the system.
2. **~15–25% of wind energy is currently wasted to curtailment.** Cutting that by even 1–2% saves millions of euros. Big impact.
   - `[VERIFIED 01-09-26]` **Resolved — it's a scope difference, not an error.** The Republic alone was ~11.3% in 2025. The 15–25% band is the *all-island to Northern Ireland* range: all-island wind dispatch-down was 14.0% in 2024 and ~15% in H1 2026, while Northern Ireland alone was 29.6% in 2024 and 21.7% in 2025. So the organiser's figure is right for the island; just be explicit about which number you are quoting, because RoI-only and all-island differ by a factor of about 1.4.
   - `[MINE]` Practical consequence: state your scope in the first slide. A 2% improvement on an 11.3% RoI baseline and a 2% improvement on a 25% NI baseline are very different claims.
3. **Too much current through a grid line will melt the cable.** (Thermal line rating — the physical origin of *constraint*.)
4. **"Braye's paradox" of network curtailment** could be worth looking into.
   - `[VERIFIED 01-09-26]` This is **Braess's paradox**: adding a link to a network can make overall flow *worse*. The power-systems version is real and published — **Dirk Witthaut and Marc Timme, "Braess's paradox in oscillator networks, desynchronization and power outage," *New Journal of Physics* 14 (2012) 083036, doi:10.1088/1367-2630/14/8/083036** (open access). Adding a transmission line can *reduce* synchronisation stability; this was the first demonstration of the paradox in oscillator networks. A strong, presentable, genuinely physics-flavoured angle.
   - `[MINE]` Caveat before you build on it: no source has been found applying Braess's paradox to the *Irish* grid specifically. That's an opportunity, but it also means you'd be demonstrating it yourself rather than citing someone who already has. **Section 8 of the Tuesday workshop notebook implements the classic four-node example**, so you have working code to build from.
5. **PyPSA is a good tool and one we'll be told to use during the hackathon.**
6. **Lack of inertia from renewable generation** could be worth looking into.
   - `[MINE]` This is the same underlying issue as **MUON** (§4). Low system inertia forces a minimum number of synchronous units to stay online, and that is what actually drives most curtailment.
7. **Ireland apparently does some kind of clustering to run the high-power grid**, mechanism unknown.
   - `[VERIFIED 01-09-26]` **Confirmed: EirGrid's constraint groups.** The source document is EirGrid's *"Wind Dispatch Tool Constraint Group Overview"*, current public edition dated **1 February 2024, 74 pages** ([PDF](https://cms.eirgrid.ie/sites/default/files/publications/Wind-Dispatch-Tool-Constraint-Group-Overview_0.pdf)). It defines **~39 named groups across seven regional categories** — Northern Ireland (5), Ireland North West (7), West (9), South West (11), South East (4), North East (2), and one nationwide group ("All IE"). *(Corrected: an earlier draft of this brief said ~15.)*
   - **How a group is defined, in EirGrid's own words:** farms are grouped "depending on their **effectiveness** to alleviate constraints… a measure of the change in wind/solar farm output relative to the change in the level of the 'base case', 'N-1' or 'N-1-1' overload," and that effectiveness "is a function of the **topology of the transmission network**." Membership rule: every Controllability Category 2 farm connected to the transmission stations in that group. Reductions are then shared **pro-rata within the group**, and a farm can sit in **several overlapping groups at once**, taking the tightest binding setpoint.
   - `[MINE]` **Two things follow, and they pull in opposite directions.** First, this is *not* graph clustering — no EirGrid document describes spectral clustering or community detection, so don't claim you've discovered their algorithm. Second, "effectiveness as a function of network topology" is exactly a sensitivity calculation on the network graph, which is something you can now compute directly (§6).
   - **The confirmed gap:** the PDF publishes group membership at the **transmission-station level only**. The named-wind-farm-to-group lookup table is genuinely not published anywhere.

---

## 4. Domain concepts to have straight before day 1

**Dispatch-down** = EirGrid instructing a wind or solar farm to reduce output. It splits into two things that need completely different optimisation approaches:

- **Curtailment** — *system-wide*. Driven mainly by:
  - **SNSP** (System Non-Synchronous Penetration): the maximum share of instantaneous generation allowed from non-synchronous sources (wind, solar, HVDC imports). Raised 50% (2015) → 65% (2018) → 70% (2021) → **75% (April 2022, current)**, target **95% by 2030**.
  - **MUON** (Minimum Number of Units Online): conventional synchronous plant that must stay running for frequency, voltage and reserve stability. **This is the inertia problem.**
- **Constraint** — *localised*. Insufficient transmission capacity in one part of the network — a traffic jam. Independent of the system-wide SNSP position. This is where thermal line limits (organiser point 3) and graph structure matter.

The split matters for money as well as physics: the curtailment/constraint distinction was approved in **SEM-13-011** and determines who gets compensated.

**The key empirical result** `[VERIFIED 01-09-26]`:

> In 2020–21, **MUON — not SNSP — drove roughly 80% of curtailment.** SNSP gets the press; MUON is the bigger lever.

Source: M. Hurtado, T. Kërçi, S. Tweed, E. Kennedy, N. Kamaluddin and F. Milano, *"Analysis of Wind Energy Curtailment in the Ireland and Northern Ireland Power Systems,"* **2023 IEEE Power & Energy Society General Meeting (PESGM)**, pp. 1–5 — preprint at [arXiv:2302.07143](https://arxiv.org/abs/2302.07143). SNSP accounted for under 20%; RoCoF and inertia were negligible.

**Read the scope carefully.** That 80% is a share of ***curtailment*** — system-wide dispatch-down only. It is not a share of *total* dispatch-down, which also includes local constraint. Two figures put it in context:

- In 2024, EirGrid attributed **96% of RoI curtailment** to MUON. The finding has strengthened, not faded.
- But in 2025, **constraints (6.6%) overtook curtailment (4.7%)** as the larger component of RoI wind dispatch-down. So MUON dominates the *curtailment* half while the *constraint* half has become the bigger half overall.

That connects organiser points 2 and 6 directly. It also means a project aimed only at the SNSP cap is addressing a small and shrinking slice of the problem.

### Scale and stakes
- All-island renewables: **40.0% of demand in 2024**, 13,288 GWh of wind generated.
- RoI wind dispatch-down reached **~11.3% in 2025** (4.7% curtailment + 6.6% constraint). All-island 2024 was **14.0%**; Northern Ireland alone **29.6%** in 2024 and **21.7%** in 2025.
- **Cost — quote this carefully.** The widely repeated **€567m** is the **Network Imperfections Charge allowed for tariff year 2024/25** (€567.21m, SEM Committee decision **SEM-25-053**) — a broader basket than curtailment, also covering make-whole payments and net imbalance energy cost. For 2025/26 the TSOs proposed **€883.24m** (€22.28/MWh, up 56%) and the SEM Committee **disallowed €93m**. The "€700m forecast" often cited is a rounding of the base forecast, not the submitted figure. *(Corrected: an earlier draft of this brief called these "constraint costs," which overstates what they measure.)*
- Every curtailed MWh is near-zero-marginal-cost clean energy displaced, typically by gas held online to satisfy MUON or a local network limit.

---

## 5. Verified findings

### The biggest data gap is closed, and it's openly licensed `[VERIFIED 01-09-26]`

The paper is now saved locally as `../03-network/nayer-2026-arxiv-2608.24464.pdf`. Reading its reference list resolved the open licence question outright — **no email needed.**

**The paper.** R. Nayer, S. Hodges, W. Bukhsh (University of Strathclyde) and C. Chitambo, C. Wijeratne (Renewable Energy Solutions), *"Modelling Renewable Curtailment and Constraints in Ireland's Electricity System"*, [arXiv:2608.24464](https://arxiv.org/abs/2608.24464), submitted 25 August 2026. A full MILP formulation of Irish curtailment and constraint, tested on a toy example and on a realistic all-island network.

**The network model — the thing you actually want.** Cited as reference [27] and deposited separately on Zenodo:

| | |
|---|---|
| **Title** | "Ireland Electricity System Model", R. Nayer, version 0.1, published 7 October 2025 |
| **DOI** | [10.5281/zenodo.17287498](https://doi.org/10.5281/zenodo.17287498) |
| **File** | `ireland_case_july2025.xlsx`, 20.0 MB |
| **Licence** | **Creative Commons Attribution 4.0 International (CC BY 4.0)** |
| **Direct download** | `https://zenodo.org/records/17287498/files/ireland_case_july2025.xlsx` |

**Contents, from §V-B of the paper:** **446 buses, 586 lines, 183 transformers, 288 generators** — a full bus/branch/generator representation of the all-island transmission system, with security-constraint definitions. Appendix A of the paper lists EirGrid's named security constraints with their MW limits (interconnector ratings, Northern Ireland reserve limits, Dublin and Cork minimum-unit requirements), which is the MUON structure written out explicitly.

**The code, also openly licensed.** Reference [26]: "richardnayer/oats_curtailment: Release for PSCC paper", [10.5281/zenodo.17358993](https://doi.org/10.5281/zenodo.17358993), a 60 MB archive of the GitHub repo, also **CC BY 4.0**. Built on **OATS** (Bukhsh, Edmunds & Bell, *IEEE Trans. Power Systems* 35(5):3552–3561, 2020), which is itself GPL-3.

> **What this means practically:** you may use the network model and the code for the hackathon, including in your Friday presentation, provided you **attribute** them. CC BY 4.0 asks for credit and nothing else. *(Corrected: the 29 August draft of this brief said the licence status was "genuinely unclear" and recommended emailing the authors. It was unclear only because the GitHub repo has no licence file — the Zenodo deposits, which are the formal release, are unambiguous. That email is no longer needed.)*

**Cite as:** Nayer, R. (2025). *Ireland Electricity System Model* (0.1) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.17287498 — alongside the arXiv paper.

### Three caveats the authors state themselves `[VERIFIED 01-09-26]`

1. **It is explicitly a draft.** The Zenodo description calls it "a draft electricity system network model for the island of Ireland that requires further refinement, including operational date validation, transformer classification improvements, and connection point rationalization." The paper adds that building it "requires significant manual review of the data to address inaccuracies and inconsistencies."
2. **N-1 security is not modelled**, so the model **underestimates constraints** — and constraints are now the larger half of the problem (§4). The paper is candid: it "under estimates total dispatch down, Constraints and MUON, while overestimating SNSP Curtailment." Their flagging logic lets SNSP bind before MUON ever can.
3. **It is Pyomo-based, not PyPSA.** Since the hackathon will point you at PyPSA, treat this as a **data** asset: convert the bus/branch/generator tables into a PyPSA network rather than adopting their solver stack. `[MINE]`

Caveats 1 and 2 are opportunities, not problems. An honest "we validated their network model" or "we added N-1 and here's what it changes" is a stronger Friday result than another dispatch simulation.

### Also worth knowing `[VERIFIED 01-09-26]`

The paper's own literature review notes that existing curtailment models "assumed a single pro-rata group, whereas **in Ireland generators can belong to multiple, and potentially overlapping, pro-rata groups**." Their handling of that (equations 16–17, using binary variables to pick the tightest binding group) is the novel part of the paper. Overlapping groups is a genuinely awkward structure, and it is the sort of thing a physics team can say something interesting about.

---

## 6. Candidate project angle `[MINE]` — rewritten 1 September 2026

> **What changed.** The 29 August version of this section proposed inferring EirGrid's constraint groups statistically, by spectral clustering on which farms get dispatched down at the same time. That was the right idea when we had no network model. We now have a 446-bus one (§5), and EirGrid have told us in their own words that groups are defined by **effectiveness — the sensitivity of an overload to each farm's output, as a function of network topology** (§3.7). That is a quantity you can compute directly from the network rather than infer from correlations. Computing it beats guessing it.

**Reconstruct EirGrid's constraint groups from the network, then check them against reality.**

Three stages, each of which stands alone if you run out of time:

1. **Compute effectiveness.** For each transmission line in the 446-bus model, work out how much each generator's output changes the flow on it — the sensitivity of line flow to injection at each bus. This is a linear algebra problem on the network, and it falls straight out of the DC power flow: it is the same Laplacian machinery as the Tuesday workshop, applied to a grid instead of a map.
2. **Group on it.** Farms with similar effectiveness vectors for a given overload are, by EirGrid's definition, the same constraint group. Cluster them and compare against the ~39 real groups in the Wind Dispatch Tool PDF — you have their names, their regions and the stations they contain, so you can score how well you recovered them.
3. **Ask whether the grouping is any good.** EirGrid's groups are pre-defined for speed in the control room, not optimality. Does dispatching down by these fixed groups waste more energy than a per-farm optimum would? That difference, in MWh and euros, is a result. Note the paper's own finding that a farm can belong to several overlapping groups and takes the tightest setpoint — pro-rata within overlapping groups is exactly the kind of rule that leaves value on the table.

**Why it fits:**
- The farm-to-group mapping is a confirmed public gap (§3.7), so stage 2 is a real contribution, not a re-implementation.
- Stage 1 is the Tuesday workshop content pointed at the actual problem.
- Stage 3 turns a descriptive result into a number with a euro sign on it, which is what the brief asks for and what presents well on Friday.
- It bridges organiser points 3, 4 and 7 — thermal limits, network topology, clustering.
- **It has a validation path**, which most hackathon projects don't: EirGrid publish the answer at station level, so you can check your work.

**Honesty constraint for the presentation.** Say "we reconstructed the grouping EirGrid uses," not "we discovered how EirGrid clusters the grid." They publish the method; what isn't published is the farm-level result.

Adjacent angles worth holding in reserve:
- **MUON-driven curtailment** as the dominant lever (§4) — the most physics, the least press coverage. Appendix A of the paper gives you the real minimum-unit constraints to work with.
- **Braess's paradox** — does a proposed network reinforcement actually help? (§3.4) Ireland has two large reinforcements with public dates (Celtic Q4 2028, North–South October 2031) and the workshop notebook has working four-node code. Nobody appears to have tested this on the Irish network.
- **Adding N-1 security** to the Nayer model, which the authors flag as the main reason it underestimates constraint (§5).
- **Battery / storage siting** — note the CleanerGrid 2025–26 winners (UCD MEng, Peter McHugh & Rory Tobin) already did battery-storage siting for curtailment, so differentiate or skip.

---

## 7. Surrounding organisations

- **TPSA** — Theoretical Physics Student Association, TCD. Runs the workshops and hackathon.
- **TPSA CLG / The Problem Solving Association** — TPSA's non-profit sister organisation, applying theoretical physics to public services. tpsa.ie/problem-solving `[EMAIL]`
  - **COTHROM** — computational Irish electoral redistricting using **Potts Hamiltonians, MCMC and simulated annealing**. arXiv preprint, covered by the Irish Times. *(Note the direct methodological overlap with the Friday MCMC workshop.)*
  - **SPARÁN** — public payments transparency tool tracking >€100bn in Irish state spending. Featured in the Irish Times and on the David McWilliams Podcast.
  - **Ecnetica** — open-source maths learning platform, in development.
- **TF Wind** — Trinity Floating Wind, offshore wind specialists, co-presenting. `[EMAIL]` `[ORGANISER]`
- **EirGrid / SONI** — transmission system operators for RoI / NI. **ESB Networks** — distribution operator. **CRU** — regulator. **SEMO / SEMOpx** — market operator.
- **Hack the Climate** — a *separate* hackathon, 28–30 Sept 2026, Microsoft Ireland Dublin, run by WindEurope, Microsoft, ESB, Hitachi, SSE and Wind Energy Ireland. Its stated mission is literally to "predict, reduce, or eliminate dispatch-down and market-based curtailment" on the Irish grid. **hacktheclimate.io** already hosts curated sample data plus a copy of the **2025** Annual Renewable Constraint and Curtailment Report. Free, public, no relationship needed — just download it.

---

## 8. Open questions to resolve on or before day 1

1. What data gets handed out at the day-1 briefing? (Avoid rebuilding it over the weekend.)
2. Is pre-hackathon prep work allowed, or frowned on?
3. Is the assessed output the Friday presentation only, or code as well?
4. Team composition — up to 5. Who?
5. Does anyone on the team have a working PyPSA install with a solver? The solver is usually where the first hour goes.

**Closed since 29 August:**
- ~~Which baseline is "15–25% wasted" measured against?~~ → all-island / Northern Ireland, not RoI (§3.2).
- ~~Can we use the Irish network case data?~~ → yes, CC BY 4.0 on Zenodo (§5).
- ~~How many constraint groups are there, and how are they defined?~~ → ~39, by electrical effectiveness (§3.7).

---

## 9. Irish terminology (from the TPSA email; unrelated, included for completeness) `[EMAIL]`

*dreige* — meteor · *dreigechith* — meteor shower · *urú na gréine* — solar eclipse · *fabhra* — eclipse (Donegal Irish) / eyelash
