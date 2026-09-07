# Rundown

**Everything in this folder, explained from nothing.**

Written for someone who has never seen this project. No prior knowledge of power
systems is assumed. Sections are independent — skip freely, and use the
[glossary](#appendix-a--glossary) whenever a term appears cold.

---

## Contents

**Part I — The problem**
[1. What a power grid actually is](#1-what-a-power-grid-actually-is) ·
[2. Why wind gets thrown away](#2-why-wind-gets-thrown-away) ·
[3. The one distinction that matters](#3-the-one-distinction-that-matters) ·
[4. How big is it](#4-how-big-is-it)

**Part II — The physics**
[5. Power does not choose its route](#5-power-does-not-choose-its-route) ·
[6. The grid is a system of springs](#6-the-grid-is-a-system-of-springs) ·
[7. PTDF, the number the project turns on](#7-ptdf-the-number-the-project-turns-on) ·
[8. Why N-1 changes everything](#8-why-n-1-changes-everything)

**Part III — What EirGrid actually does**
[9. Constraint groups](#9-constraint-groups) ·
[10. Why this leaves value on the table](#10-why-this-leaves-value-on-the-table)

**Part IV — What we built**
[11. The data](#11-the-data) ·
[12. The pipeline](#12-the-pipeline)

**Part V — What we found**
[13. Wind does not decorrelate across Ireland](#13-wind-does-not-decorrelate-across-ireland) ·
[14. The weather model works](#14-the-weather-model-works) ·
[15. MUON, not SNSP](#15-muon-not-snsp) ·
[16. Groups are not weather](#16-groups-are-not-weather) ·
[17. Groups *are* effectiveness](#17-groups-are-effectiveness) ·
[18. Smaller findings](#18-smaller-findings)

**Part VI — What is not done**
[19. N-1](#19-n-1) ·
[20. The clustering, and two decisions](#20-the-clustering-and-two-decisions) ·
[21. Where MCMC might come in](#21-where-mcmc-might-come-in) ·
[22. Stage 3: the euro figure](#22-stage-3-the-euro-figure)

**Appendices**
[A. Glossary](#appendix-a--glossary) ·
[B. Folder map](#appendix-b--folder-map) ·
[C. The numbers, with their scope](#appendix-c--the-numbers-with-their-scope)

---
---

# Part I — The problem

## 1. What a power grid actually is

A power grid is a graph. **Nodes** (called *buses*) are substations. **Edges**
(*lines* and *transformers*) carry power between them. Generators inject power at
some nodes; loads withdraw it at others.

Ireland's transmission grid — the high-voltage skeleton, not the poles in your
street — has roughly **446 buses and 775 branches** operating at 110 kV, 220 kV,
275 kV and 400 kV. Higher voltage carries more power with fewer losses, which is
why long-distance transmission is high-voltage.

Two physical facts drive everything else:

**Electricity is not stored in the wires.** Generation must equal consumption at
every instant, everywhere, continuously. There is no buffer. If they drift apart,
system frequency moves off 50 Hz, and far enough off, equipment disconnects to
protect itself.

**Every line has a thermal limit.** Current heats a conductor; a hot conductor
sags and can arc to something below it. So each line has a maximum power it may
carry. Exceed it and you risk losing the line — and its power has to go
somewhere, which can cascade.

That second fact is the origin of the whole problem. **A line that is full is a
line that cannot take your wind.**

## 2. Why wind gets thrown away

Ireland has a lot of wind, and it is in the wrong place.

The wind resource is on the **Atlantic seaboard** — Donegal, Mayo, Galway, Kerry.
The demand is in **Dublin**, on the other side of the country. Between them is a
relatively weak network built decades ago to serve towns, not to move gigawatts
west to east.

So on a windy night with low demand you can have more wind available in Mayo than
the lines out of Mayo can carry. Something has to give, and what gives is the
wind: EirGrid instructs farms to reduce output. This is **dispatch-down**.

The energy is simply lost. It cannot be stored at scale, cannot be moved, and is
usually replaced by gas — so every dispatched-down megawatt-hour is clean energy
displaced by fossil generation.

## 3. The one distinction that matters

**If you remember one thing from this document, make it this.** Dispatch-down is
two different phenomena with the same symptom, and they need opposite solutions.

|  | **Curtailment** | **Constraint** |
|---|---|---|
| Scope | System-wide | Local |
| Cause | The whole island cannot absorb it | One corridor is full |
| Analogy | Nationwide speed limit | One blocked road |
| Fixed by | Storage, flexibility, interconnectors | Reinforcement, redispatch, siting |
| Ireland, 2025 | 4.7% | 6.6% |

**Curtailment** happens because the system as a whole cannot safely take more
non-synchronous power. Two limits drive it:

- **SNSP** — System Non-Synchronous Penetration. The maximum share of
  instantaneous generation allowed from sources that are not spinning in
  synchrony with the grid: wind, solar, HVDC imports. Currently capped at **75%**.
- **MUON** — Minimum Number of Units Online. A floor on how many conventional
  synchronous generators must keep running, regardless of whether they are
  needed for energy.

**Constraint** is local. A bottleneck in Mayo curtails farms in Mayo. A farm in
Wexford is unaffected. This is where network topology matters, and it is the half
this project addresses.

> **Why MUON exists — the inertia problem.** A conventional power station has a
> massive turbine spinning at 3,000 rpm. That rotating mass stores kinetic energy
> and is *physically coupled* to grid frequency. If demand suddenly rises,
> the spinning mass gives up energy and slows fractionally — buying seconds
> before anything has to act.
>
> A wind turbine connects through power electronics. It is **decoupled** from
> grid frequency and contributes no inertia. So a grid running mostly on wind has
> very little rotational inertia, and frequency can move dangerously fast after a
> fault. MUON forces enough spinning machines to stay online to keep that rate of
> change survivable.
>
> **This is why curtailment happens even when no line is full.** It is not a
> capacity problem. It is a stability problem, and it is fundamentally about the
> physics of rotating mass.

## 4. How big is it

In 2025, **11.3% of all available wind in the Republic was thrown away** — 6.6%
constraint, 4.7% curtailment. All-island it was 14.0% in 2024; Northern Ireland
alone hit 29.6%.

And it is getting worse fast — from about 3% in 2016 to 13–24% in 2026 depending
which region you look at. See [charts/01-dispatch-down-trend.png](07-figures/charts/01-dispatch-down-trend.png).

**Always state which figure you are quoting.** Republic, all-island and Northern
Ireland differ by a factor of about 2.6. Quoting the wrong one is the easiest
error to make. See [Appendix C](#appendix-c--the-numbers-with-their-scope).

---
---

# Part II — The physics

## 5. Power does not choose its route

Here is the fact that makes grids hard, and it surprises people every time.

**Power does not flow along the route you would pick. It flows along every
available path at once, in proportions set by physics.**

Send 1 MW from A to C in a network where a direct line exists *and* a longer path
through B exists, and the power does not take the short way. It splits — most on
the direct line, some the long way round — in inverse proportion to the electrical
impedance of each path.

Three consequences that shape this entire project:

1. **You cannot route power.** There are no valves. You can only change where it
   is injected and withdrawn, and let physics do the rest.
2. **A generator affects lines nowhere near it.** Turning down a farm in Mayo
   changes flows across the whole island, by amounts you have to compute.
3. **Adding a line can make things worse.** This is [Braess's
   paradox](https://doi.org/10.1088/1367-2630/14/8/083036), and it is real in
   power networks, not just a curiosity in traffic.

## 6. The grid is a system of springs

Now the useful part, and the reason a physics student has an advantage here.

The full equations of AC power flow are nonlinear and unpleasant. But
transmission networks sit in a regime where a clean approximation holds. Assume:

- voltage magnitudes are all ≈ 1 per unit (true, they are tightly regulated)
- resistance is negligible next to reactance (true at transmission voltages)
- angle differences between neighbouring buses are small, so `sin θ ≈ θ`

Under those assumptions — the **DC power flow approximation** — the power flowing
along a line becomes beautifully simple:

$$P_{ij} = \frac{\theta_i - \theta_j}{x_{ij}}$$

where θ is the voltage phase angle at a bus and *x* is the line's reactance.

**Look at what that is.** Flow is proportional to a *difference* between nodes,
divided by a property of the edge. That is Hooke's law. θ plays the role of
displacement, 1/x the role of a spring constant, and power the role of force.

**A power grid, in this approximation, is a network of springs.**

Collect it in matrix form. Let **A** be the branch–node incidence matrix (+1 and
−1 marking each line's endpoints). Then bus power injections **p** relate to
angles **θ** by:

$$\mathbf{p} = \mathbf{B}\,\boldsymbol{\theta}, \qquad
  \mathbf{B} = \mathbf{A}^{\mathsf T}\,\mathrm{diag}(1/x)\,\mathbf{A}$$

**B** is the **graph Laplacian**, weighted by 1/x — the same operator from the
Tuesday workshop, where `L = D − A` and the quadratic form `xᵀLx` summed squared
differences across edges. Same matrix. Same maths. The workshop taught the
unweighted version on a map of Dublin; the grid uses the susceptance-weighted
version. That is the only difference.

This is why graph theory is the right tool, and it is not a metaphor. The DC
power flow *is* a Laplacian problem.

> **One subtlety.** **B** is singular — adding a constant to every angle changes
> nothing physical, exactly as a spring network has no absolute position. You fix
> it by nominating a **reference (slack) bus**. That choice is arbitrary but not
> harmless, and §7 shows where it bit us.

## 7. PTDF, the number the project turns on

Invert the relation and you can ask the question that matters:

**If I inject 1 MW at this bus, how much of it flows along that line?**

That number is the **Power Transfer Distribution Factor**. Derived directly:

$$\boldsymbol{\theta} = \mathbf{B}^{+}\mathbf{p}
\quad\Longrightarrow\quad
\text{PTDF} = \mathrm{diag}(1/x)\,\mathbf{A}\,\mathbf{B}^{+}$$

where **B⁺** is the pseudo-inverse. One matrix: rows are lines, columns are buses.

**A worked example you can check by hand.** Three buses in a triangle, all lines
with the same reactance *x*. Inject 1 MW at A, take it out at C:

```
   A ─────────── C      direct path:  reactance x
    \           /
     \         /        long path:    reactance 2x (via B)
      \       /
         B
```

Parallel paths divide current inversely with impedance, so the direct line takes
**2/3** and the long way takes **1/3**. Note the answer does not depend on the
value of *x* — only on the ratio.

We ran exactly this test before trusting anything else, and PyPSA reproduced
2/3 and 1/3 to machine precision. **8 of 8 checks passed**
([verify_ptdf.py](03-network/scripts/verify_ptdf.py)).

### Why PTDF *is* the project

EirGrid's published definition of a constraint group:

> "Wind/solar farms are grouped together depending on their **effectiveness** to
> alleviate constraints… a measure of the change in wind/solar farm output
> relative to the change in the level of the overload. The effectiveness of each
> wind/solar farm is a **function of the topology of the transmission network**."

Read that carefully. "Change in the overload per change in farm output, as a
function of network topology" **is a PTDF**. It is not similar to one; it is one.

So the project is not inventing a method. It is recomputing EirGrid's own
definition from the network they operate — using only public data.

## 8. Why N-1 changes everything

Grids are not planned to survive normal operation. They are planned to survive
**the loss of any single component** — a line tripping in a storm, a transformer
faulting. That standard is called **N-1**: the system must remain secure with N
components when any 1 is removed.

This changes what "full" means. A line running at 60% of its limit may be
perfectly safe today and completely unacceptable, because if the parallel circuit
trips, *this* line inherits its flow and overloads instantly.

**So the binding limit is usually not the flow now. It is the flow after the
worst credible failure.**

The matrix for this is the **LODF** (Line Outage Distribution Factor): if line *k*
trips, what fraction of its flow lands on line *l*? PyPSA calls it **BODF** and
computes it in one call, `calculate_BODF()`.

This matters here because EirGrid's own wording defines effectiveness against
*"the 'base case', 'N-1' or 'N-1-1' overload"*. **N-1 is inside the definition of
the thing we are reconstructing** — so a base-case-only answer is incomplete.
This is the largest known gap in the current work (§19).

---
---

# Part III — What EirGrid actually does

## 9. Constraint groups

When a corridor is congested, EirGrid does not optimise each farm individually.
There is no time — control-room decisions happen in minutes.

Instead they pre-compute **constraint groups**: sets of farms that are similarly
effective at relieving a particular overload. The operator picks a group, enters
a megawatt reduction, and the Wind Dispatch Tool shares that reduction
**pro-rata** among the members.

The public document defines **39 numbered groups** across seven regions:

| Region | Groups |
|---|---|
| Ireland South West | 11 |
| Ireland West | 9 |
| Ireland North West | 7 |
| Northern Ireland | 5 |
| Ireland South East | 4 |
| Ireland North East | 2 |
| Nationwide ("All IE") | 1 |

The concentration in the west and south-west is not an accident — that is where
the wind is and the network is weakest.

Two structural features matter a great deal:

- **Groups overlap.** A farm can belong to several at once and takes the tightest
  binding setpoint. In our data, farms carry up to four group tags.
- **Membership is published at station level only.** The document names
  transmission stations, never individual farms. Your briefing documents call the
  farm-level mapping a confirmed public gap — and it is, from EirGrid. We found
  it reconstructed inside the Nayer network model instead (§11).

## 10. Why this leaves value on the table

Pro-rata within a fixed group is **fast**, which is what a control room needs. It
is not **optimal**.

Within one group, farms differ in effectiveness. Cutting a highly effective farm
by 10 MW might relieve the overload as much as cutting a poorly-placed one by
30 MW. Pro-rata ignores that and cuts everyone by the same proportion.

The waste is the difference between what a pro-rata reduction costs and what a
per-farm optimum would cost, in megawatt-hours and euro. **Quantifying that is
Stage 3 of the project** (§22), and it needs PTDF to exist.

We already know where to look. Group `ROI-W/2` has 95 members — essentially "all
of the West" — and our test found it is the one group that is *not* electrically
coherent (§17). A catch-all group is exactly where a per-farm optimum should win
biggest.

---
---

# Part IV — What we built

## 11. The data

Everything here is public and openly licensed. Nothing needed permission.

| What | Source | Why it matters |
|---|---|---|
| **Network model** — 446 buses, 775 branches, impedances, ratings | Nayer (2025), Zenodo, CC BY 4.0 | The grid as a graph. Everything physical depends on it |
| **Constraint groups** — 39 groups, 99 stations | EirGrid WDT document, parsed from a 74-page PDF | The answer we are trying to reconstruct |
| **Dispatch-down by reason** — monthly, 2016–2026 | EirGrid | Ground truth: how much, and why |
| **System state** — every 15 minutes | EirGrid, full-year 2025 and Jan–Jul 2026 | Wind available vs generated; the difference *is* dispatch-down |
| **Wind farms** — 313 sites, capacity, connection node | SEAI, CC BY 4.0 | Links farms to the network |
| **Wind speed** — hourly, any period | ERA5 via Open-Meteo, CC BY 4.0 | The weather layer |
| **Contracted pipeline** — 24 future farms | EirGrid, Nov 2025 | What is coming, and where |

**The find.** The Nayer model's `generator` sheet carries a `prorata_groups`
column, populated for all 294 generators, mapping named farms to constraint
groups in EirGrid's own naming — with overlapping membership explicit:

```
Sliabh Bawn Windfarm      ->  ROI-NW/4, ROI-W/1, ROI-W/2, ROI/1
Molly Mountain Wind Farm  ->  NI/2, NI/3, NI/4
```

This is the mapping the briefings call unpublished. EirGrid do not publish it —
but a researcher reconstructed it and released it openly. That converts the
project's Stage 2 from *inventing* an answer with no way to check it, into
*validating and extending* one against a real target.

**Three things genuinely are not available, to anyone:** per-farm dispatch-down
volumes, which named constraint was binding at a given moment, and real turbine
power curves per site. No amount of searching will find them.

## 12. The pipeline

Roughly 20 scripts, each re-runnable from scratch, in dependency order:

```
    xlsx model  ──► PyPSA network ──► PTDF ──► effectiveness per farm per line
                                                          │
    SEAI farms  ──► coordinates ──► ERA5 wind ──► MW      │
         │                                        │       │
         └────────► joined to buses ──────────────┴───────┘
                                                          │
    EirGrid reports ──► reason codes, 15-min state ───────┘
```

Every script writes to a `script-output/` folder and can be deleted and rebuilt.
Nothing is hand-edited. See [Appendix B](#appendix-b--folder-map).

---
---

# Part V — What we found

Five findings. Two are strong enough to lead a presentation.

## 13. Wind does not decorrelate across Ireland

**Question.** Is Ireland big enough that wind in Donegal is independent of wind
in Cork? If so, geographic spread would smooth output and reduce curtailment.

**Method.** For all 48,828 pairs of the 313 farms, compute great-circle distance
and correlate their hourly wind speeds. Fit `corr(d) = exp(−d/L)`; **L** is the
decorrelation length.

**Result.**

| Distance apart | Correlation (July) | Correlation (January) |
|---|---|---|
| 25–50 km | 0.898 | 0.931 |
| 100–150 km | 0.746 | 0.829 |
| 200–400 km | **0.550** | **0.657** |

**L = 460 km in summer, 599 km in winter.** Ireland's longest dimension is about
450 km. **The decorrelation length exceeds the country.**

**Why.** Atlantic weather systems are synoptic-scale — 1,000 km and more. Ireland
sits inside a single such system. When it is windy, it is windy nearly everywhere
at once.

**What follows.** Curtailment events are national and near-simultaneous. **You
cannot fix curtailment by spreading wind farms further apart** — and least of all
in winter, when correlation is *higher* and curtailment is worst. The lever must
be the network and system operation, not siting.

📊 [charts/05-wind-correlation-by-distance.png](07-figures/charts/05-wind-correlation-by-distance.png)

## 14. The weather model works

**Question.** Can a simple physical model reproduce what EirGrid actually
measures?

**Method.** Take ERA5 wind speed at each farm's coordinates, push it through a
generic turbine power curve, sum to a fleet total. Compare hour by hour against
EirGrid's published wind *availability*. No fitting, no tuning, no EirGrid data
used as input.

The power curve is the physics:

| Wind speed | Output | Why |
|---|---|---|
| below 3 m/s | zero | not enough torque to turn |
| 3 → 12 m/s | rises as **v³** | kinetic energy flux is ½ρAv³ |
| 12 → 25 m/s | flat at rated | generator capacity reached; blades pitch to spill |
| above 25 m/s | zero | shut down to avoid damage |

That **v³** is worth internalising: a 20% rise in wind speed is a **73%** rise in
available power. Small meteorological changes are large electrical ones.

**Result over 5,087 hours:**

| | |
|---|---|
| Correlation | **r = 0.984 (r² = 0.968)** |
| Bias | −3.8% |
| RMSE | 253 MW (5.9% of fleet capacity) |

**What follows.** The pipeline is validated, not assumed. The small negative bias
is explained — the farm list is from 2022 and misses newer capacity.

**Important limit.** It predicts *availability*, not generation. The difference
between them **is** curtailment, and the model knows nothing about that.

📊 [charts/11-model-vs-eirgrid-measured.png](07-figures/charts/11-model-vs-eirgrid-measured.png)

## 15. MUON, not SNSP

**Question.** Which limit actually causes curtailment?

SNSP gets the attention — it is a single headline percentage that sounds like the
binding constraint.

**Result, computed from EirGrid's own reason codes:** in 2024, **96.3%** of
all-island curtailment was attributed to minimum-units-online. SNSP accounted for
a few percent; RoCoF and inertia were negligible.

**What follows.** A project that only attacks the SNSP cap is addressing a small
slice. The real lever is the requirement to keep conventional plant spinning —
the inertia problem from §3.

Note the scope: that is a share of **curtailment**, not of total dispatch-down.
Since 2025, *constraint* is the larger half overall.

📊 [charts/03-curtailment-causes.png](07-figures/charts/03-curtailment-causes.png)

## 16. Groups are not weather

**Question.** Could constraint groups just be "farms that are near each other and
therefore windy together"? If so, weather data alone would reconstruct them.

**Method.** For each group, measure the mean pairwise wind correlation of its
members. Compare against what distance *alone* predicts. Groups are geographically
compact, so they will trivially be correlated — the honest test is whether they
beat the distance-only prediction.

**Result.** Every group is far more correlated than random farms — but against the
distance prediction, only **1 of 12** beats it. Mean residual **−0.019**.

**What follows.** **Constraint groups carry no weather information beyond
proximity.** You cannot recover them from meteorological data. The information is
somewhere else.

## 17. Groups *are* effectiveness

**Question.** The same test, but using computed electrical effectiveness instead
of weather. Are group members more alike in their PTDF vectors than random farms?

**Method.** Each farm gets a vector: its effectiveness against all 770 branches.
Measure mean pairwise cosine similarity within each real group; compare against
500 random farm sets of the same size.

**Result.**

| | Weather | Effectiveness |
|---|---|---|
| Groups beating the null | **1 of 12** | **11 of 12** |
| Mean excess | −0.019 | **+0.384** |

Group `ROI-W/4` reaches cosine similarity **1.000** — its six farms have
effectively identical effectiveness vectors.

**What follows.** Same groups, same method, opposite answer. **EirGrid's stated
method is confirmed from the outside, using only public data.** The grouping is
electrical, and it is now measurable.

**The one failure is a gift.** `ROI-W/2` has 95 members — "all of the West" — and
is *not* electrically coherent. That is precisely where a per-farm optimum should
beat fixed pro-rata, which points straight at Stage 3.

📊 [charts/13-weather-vs-effectiveness.png](07-figures/charts/13-weather-vs-effectiveness.png) — the strongest single slide

## 18. Smaller findings

**The slack bus nearly fooled us.** PTDF assumes balancing power is withdrawn at
one reference bus. PyPSA picked one in Northern Ireland, which made every line
near it look exposed to every farm in Ireland. The fix — a capacity-weighted
distributed slack, matching how EirGrid share a pro-rata reduction — moved the
most wind-exposed lines to **Galway and the West**, where EirGrid's groups
actually concentrate. *The correction validated itself.*

**Line ratings in the model never vary.** All 586 line ratings are constant across
July. That is a static-ratings assumption — precisely what **dynamic line rating**
(already trialled in Ireland, targeting ~30% more capacity on existing circuits)
exists to relax. A ready-made angle.

**Flat attribution is provably wrong.** Splitting measured dispatch-down pro-rata
across all farms gives every farm 14–16%, from Donegal to Wexford. We know that
is wrong. The flatness *measures* how much a location-blind method misses.

**Greenlink is missing from the briefings.** They list EWIC, Moyle, Celtic and
North–South. The live system data shows a fifth interconnector, Greenlink, active
in 89% of periods at a mean +313 MW.

**Braess is citeable but unclaimed.** The Witthaut & Timme reference checks out.
Still true: **nobody has applied Braess's paradox to the Irish grid.** Doing so
would be original.

---
---

# Part VI — What is not done

## 19. N-1

**The largest known gap.** All effectiveness so far is base-case: flows on an
intact network. EirGrid define effectiveness against *"base case, N-1 or N-1-1"*
overloads, so **contingency analysis is inside the definition**, not an
enhancement.

Mechanically it is one call — `sub_network.calculate_BODF()` — now that the
network loads. Conceptually it changes the answer: a farm that barely helps an
intact line may be critical after a nearby circuit trips.

This is also the known weakness of the underlying model: its author states N-1 is
not modelled, which is why it *underestimates* constraint. Adding it is both a
correction and a differentiator.

## 20. The clustering, and two decisions

We can compute effectiveness. We have not yet clustered on it. Two choices block
that, and both are genuine judgement calls.

### Decision 1 — overlapping or disjoint?

**The trap.** EirGrid's groups **overlap** — farms carry up to four tags. Standard
clustering (k-means, spectral) produces **disjoint, exhaustive** partitions:
every point in exactly one cluster.

**So the standard tool cannot produce the shape of the answer.**

Options:
- **Fuzzy c-means** — each farm gets a membership weight per cluster
- **Non-negative matrix factorisation** — decomposes into overlapping parts
- **Per-constraint thresholding** — for each line, take every farm above an
  effectiveness threshold. Overlap emerges naturally, and this is closest to what
  EirGrid actually describe

*Recommendation: the third. It is simplest and most faithful to the source.*

### Decision 2 — how do you score it?

You cannot say "we recovered 70% of the groups" until you define what that means.
**ARI and NMI assume disjoint partitions** and will not work.

Options: the **omega index**, **overlapping NMI**, or simply **per-group
precision and recall** on station sets. The last is least fashionable and easiest
to explain to a judge.

## 21. Where MCMC might come in

You have a Potts-model Metropolis implementation from the Friday workshop, and
the sister project COTHROM used exactly this machinery for electoral
redistricting. So: does it belong here?

**What MCMC is, briefly.** A way to sample from a probability distribution you
cannot write down directly, by taking a random walk that visits states in
proportion to their probability. In physics you use it for the Potts model — spins
on a lattice, each in one of *q* states, energy lower when neighbours agree.
Applied to optimisation, you cool the temperature (**simulated annealing**) and
the walk settles into low-energy configurations.

**The honest answer: it depends on Decision 1.**

- If you cluster effectiveness vectors with spectral methods or thresholding, the
  answer is **deterministic and fast**. MCMC adds nothing.
- MCMC earns its place only if you write a **partition objective with constraints
  that have no closed form** — contiguity, group-size limits, or overlapping
  membership. Then the map is natural: **spin = which group a farm belongs to**,
  **graph = the effectiveness network**, **energy = how badly the partition
  performs**.

That second version is a real and attractive project. But it should be a
deliberate decision, not a drift into using a technique because there was a
workshop on it.

## 22. Stage 3: the euro figure

The result that carries a presentation.

EirGrid's groups are fixed and pro-rata because control rooms need speed. That
costs energy. **How much?**

Method: for each real congestion event, compute what a pro-rata reduction within
the fixed group costs in megawatt-hours, then what a per-farm optimum — using the
effectiveness we now have — would have cost. The difference, annualised and
priced, is the answer.

This needs a DC optimal power flow: minimise cost subject to every line staying
within limits. PyPSA does it in one call, and the solver is installed and tested.

Two honesty points to state before a judge does: per-farm dispatch-down data is
not public, so any per-farm figure is **modelled, not measured**; and the
underlying network model is a draft that underestimates constraint.

---
---

# Appendix A — Glossary

| Term | Meaning |
|---|---|
| **Bus** | A node in the grid. Physically, a substation busbar |
| **Branch** | An edge: a line or a transformer |
| **Reactance (x)** | Opposition to AC current from inductance. At transmission voltages it dominates resistance, so flows are set by *x* |
| **Per unit** | Normalised units — quantities divided by a chosen base (here 100 MVA). Makes voltage levels comparable |
| **DC power flow** | Linear approximation to AC flow: flat voltages, no losses, small angles. Turns the grid into a Laplacian problem |
| **Slack bus** | The reference node that absorbs any imbalance. Arbitrary but consequential |
| **PTDF** | Power Transfer Distribution Factor. Fraction of 1 MW injected at a bus that flows on a given line |
| **LODF / BODF** | Line Outage Distribution Factor. Fraction of a tripped line's flow that lands on another line |
| **N-1** | Security standard: survive the loss of any single component |
| **Dispatch-down** | An instruction to a renewable generator to reduce output |
| **Curtailment** | System-wide dispatch-down (SNSP, MUON) |
| **Constraint** | Local dispatch-down (a full corridor) |
| **SNSP** | System Non-Synchronous Penetration. Share of generation from non-synchronous sources. Capped at 75% |
| **MUON** | Minimum Number of Units Online. Floor on conventional plant running for stability |
| **Inertia** | Kinetic energy in spinning generator masses, resisting frequency change |
| **RoCoF** | Rate of Change of Frequency. Limited to ±1.0 Hz/s |
| **Constraint group** | A set of farms similarly effective at relieving one overload |
| **Pro-rata** | Sharing a reduction in proportion to output |
| **Capacity factor** | Actual output ÷ theoretical maximum. Irish wind ≈ 24% annually |
| **MEC** | Maximum Export Capacity — the grid-relevant rating of a farm |
| **ERA5** | ECMWF's reanalysis: a physics-based reconstruction of past weather |
| **Reanalysis** | A *hindcast*, not a forecast. Uses observations taken after the fact |
| **PyPSA** | Python for Power System Analysis. The library that turns the network tables into physics |
| **EirGrid / SONI** | Transmission system operators for the Republic / Northern Ireland |

# Appendix B — Folder map

Every folder has the same three subfolders: **`data/`** (downloaded, never edit),
**`scripts/`** (our code), **`script-output/`** (generated, safe to delete and
rebuild).

| Folder | Contents |
|---|---|
| [01-brief/](01-brief/) | The event, the plan, open decisions, TODO |
| [02-curtailment/](02-curtailment/) | Why wind is wasted; EirGrid reports and extracted series |
| [03-network/](03-network/) | The grid model, constraint groups, **PyPSA and PTDF** |
| [04-meteorology/](04-meteorology/) | Farm locations, wind pipeline, forecast, validation |
| [05-workshops/](05-workshops/) | Graph theory notebooks, MCMC material |
| [06-reference/](06-reference/) | Source catalogue and data scope audit |
| [07-figures/](07-figures/) | Thirteen charts, one script |
| [08-analysis/](08-analysis/) | Work combining several folders |

# Appendix C — The numbers, with their scope

Quote the scope with the number, always.

| Measure | Value |
|---|---|
| RoI wind dispatch-down, 2025 | **11.3%** (6.6 constraint + 4.7 curtailment) |
| All-island, 2024 | **14.0%** (2,181 GWh) |
| Northern Ireland, 2024 | **29.6%** |
| Northern Ireland, 2025 | 21.7% |
| All-island renewables share of demand, 2024 | 40.0% |
| All-island wind generated, 2024 | 13,288 GWh |
| SNSP cap (current) | 75%, target 95% by 2030 |
| MUON share of curtailment, 2024 | 96.3% |

**On cost, be careful.** The widely quoted **€567m** is the *Network Imperfections
Charge allowed for tariff year 2024/25* (SEM-25-053) — a broader basket that also
covers make-whole payments and imbalance costs. It is **not** "the cost of
curtailment", and calling it that is an easy way to lose credibility.

---

*Last updated 5 September 2026. Every figure here is reproducible by running the
scripts in the folders named above.*
