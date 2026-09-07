# 08 — Analysis

Work that combines two or more of the earlier folders. Nothing here is a
download; every file is produced by a script you can re-run.

Folders 02–04 each hold one kind of thing. This folder is where they meet.

**Layout.** `scripts/` the five analyses · `script-output/` their results. No `data/` — everything is read from other folders

---

## Files, in the order they were built

Each depends on the ones above it.

### 1. [scripts/audit_join.py](scripts/audit_join.py) → [script-output/join-coverage-gaps.csv](script-output/join-coverage-gaps.csv)
**Do the two routes to a farm's constraint groups ever contradict each other?**

There are two independent ways to find which groups a farm belongs to:

```
route A   farm -> model generator -> prorata_groups      (Nayer's reconstruction)
route B   farm -> SEAI node -> WDT station -> groups     (EirGrid's own document)
```

Of 112 farms where both routes exist, 92 agree. The finding is what the other
20 turn out to be:

| Outcome | Count |
|---|---|
| Both routes share a group | 92 (82%) |
| Route A says nationwide only; route B adds a regional group | 20 (18%) |
| **Genuine contradiction** | **0** |

**The two sources never disagree.** One is simply incomplete. Every one of the
20 has route A returning `ROI/1` — the nationwide "All IE" group — where route B
also names a regional one.

The regions route A never assigns:

| Region | Farms | Capacity |
|---|---|---|
| ROI-SE (South East) | 16 | 269 MW |
| ROI-NW (North West) | 4 | 71 MW |
| ROI-W (West) | 4 | 71 MW |

This quantifies the hole exactly: the network model has **no South-East groups at
all**, so its farms there fall back to the nationwide group. Filling that is a
concrete, bounded contribution.

### 2. [scripts/wind_by_bus.py](scripts/wind_by_bus.py) → [script-output/wind-by-bus-summary-2025-07.csv](script-output/wind-by-bus-summary-2025-07.csv)
**Puts wind onto the network.**

The meteorology folder produces power per *farm*; power flow needs injection per
*bus*. This aggregates one to the other using the join, and is the input any
PTDF or DC-OPF work will need.

**58 buses carry wind, 129 farms, 3,201 MW placed.** 1,104 MW (26%) cannot be
placed because those farms have no matched model generator — reported, not
hidden. The full matrix is saved alongside: `script-output/wind-by-bus-matrix-2025-07.npy`
(58 buses × 744 hours) with `script-output/wind-by-bus-row-order.csv` giving its row order.

The largest wind buses are all in the West — the same region that holds the most
constraint groups.

### 3. [scripts/groups_vs_weather.py](scripts/groups_vs_weather.py) → [script-output/groups-vs-weather-test.csv](script-output/groups-vs-weather-test.csv)
**Are constraint groups just geography in disguise?**

Farms in a group sit near each other, so their wind is obviously correlated. The
real question is whether they are correlated *more than any other pair the same
distance apart*. Method follows the Session 2 workshop capstone: measure a
quantity across the partition, then test it against a null that holds constant
what you do not care about — here, distance.

| Result | Value |
|---|---|
| Groups tested (4+ farms) | 12 |
| More correlated than random farm sets | 12 of 12 |
| **Beating a distance-only prediction** | **1 of 12** |
| Mean residual | **−0.019** |

**Constraint groups carry no wind information beyond proximity.** Their
correlation is fully explained — very slightly over-explained — by how close the
farms are.

That is the answer EirGrid's own documentation predicts: they group on
*electrical effectiveness*, a property of network topology, not on weather. It
also settles a practical question: **you cannot recover the groups from weather
data.** You need the network. That is the case for computing PTDF.

### 4. [scripts/curtailment_per_farm.py](scripts/curtailment_per_farm.py) → [script-output/curtailment-per-farm-2026.csv](script-output/curtailment-per-farm-2026.csv), [script-output/curtailment-per-group-2026.csv](script-output/curtailment-per-group-2026.csv)
**Per-farm curtailment at hourly resolution — a figure nobody publishes.**

EirGrid publish Irish wind availability and generation every 15 minutes; their
difference is measured dispatch-down. Our wind model reproduces that availability
per farm at r² = 0.97. Combining them attributes the measured total to individual
farms.

Over January–July 2026, EirGrid measured **14.6% of available Irish wind
dispatched down**. Attributing that across 313 farms gives **1,188 GWh**, which
is 15.2% of our modelled availability — the small difference between the two
rates is the model's −3.8% level bias, not a separate result.

> **Read the result carefully — it argues against itself, and that is the point.**
>
> The attribution is pro-rata by available output. That is faithful to EirGrid's
> method for **curtailment**, which is applied pro-rata across the fleet. It is
> wrong for **constraint**, which is local: a bottleneck in Mayo does not curtail
> a farm in Wexford.
>
> You can see the consequence in the output. Across all 313 farms the estimate
> spans just **14.1% to 16.0%** — a spread of under two points, from Donegal to
> Wexford. We know that is wrong: the West is far more constrained than the east.
> **The flatness of this answer measures how much a location-blind method
> misses**, and constraint is now the larger half of dispatch-down.
>
> PTDF is what replaces the flat split with a physical one.

The small spread that does exist is a real signal: it reflects *when* each farm
is windy relative to when dispatch-down happens, which is a temporal effect, not
a locational one.

Group totals overlap by construction — a farm in four groups contributes to all
four — so those rows must never be summed.

### 5. [scripts/groups_vs_effectiveness.py](scripts/groups_vs_effectiveness.py) -> [script-output/groups-vs-effectiveness-test.csv](script-output/groups-vs-effectiveness-test.csv)
**The test the whole project rests on.**

EirGrid say they group farms by electrical effectiveness. Now that effectiveness
is computed, that claim can be checked from the outside: are the members of a
real constraint group more alike, across all 770 branches, than an arbitrary set
of farms the same size?

Same null-model method as the weather test, so the two are directly comparable.

| | Weather | Effectiveness |
|---|---|---|
| Groups beating the null | **1 of 12** | **11 of 12** |
| Mean excess | -0.019 | **+0.384** |

**The grouping is electrical, and it is now measurable.** `ROI-W/4` reaches a
cosine similarity of 1.000: its six farms have effectively identical
effectiveness vectors.

The single failure is informative rather than awkward. `ROI-W/2` has 95 members,
essentially "all of the West", and is not electrically coherent. A catch-all
group is exactly where a per-farm optimum should beat fixed pro-rata, which is
Stage 3 of the project.

### 7. N-1 and clustering — added 6 September

| Script | Output | What it establishes |
|---|---|---|
| [scripts/groups_vs_n1_effectiveness.py](scripts/groups_vs_n1_effectiveness.py) | [script-output/groups-vs-n1-effectiveness-test.csv](script-output/groups-vs-n1-effectiveness-test.csv) | Worst-case N-1 explains the groups WORSE: 5/12, mean excess -0.124 |
| [scripts/n1_feature_comparison.py](scripts/n1_feature_comparison.py) | [script-output/n1-feature-comparison.csv](script-output/n1-feature-comparison.csv) | Why: it was the method, not the grid |
| [scripts/clustering_options.py](scripts/clustering_options.py) | [script-output/clustering-options-scores.csv](script-output/clustering-options-scores.csv), [script-output/clustering-options-per-group.csv](script-output/clustering-options-per-group.csv) | Three clustering methods, scored. **No choice made** |

**The N-1 story, in full.** Worst-case-over-contingencies takes, for each farm
and line, the maximum over 714 different outages - so two farms in the same group
may peak under *different* outages and their vectors are not comparable. Building
a fairer feature (base case plus the same top 20 contingencies for every farm)
restores the result exactly:

| Feature | Beats null | Mean excess |
|---|---|---|
| A base case | 11/12 | **+0.384** |
| B worst case over N-1 | 5/12 | -0.124 |
| C base + top 20 contingencies | 11/12 | **+0.383** |

So N-1 adds no *grouping* information beyond the base case, and destroys none.
**For clustering, use base-case effectiveness** - simpler and just as good. N-1
remains essential for identifying which lines and outages are at risk, which is a
different question.

**Clustering: coherent is not the same as reconstructable.** All three methods
were calibrated to the real overlap level (1.88 memberships per farm) so the
comparison is like-for-like:

| Method | Clusters | Memb/farm | Omega | Best-match F1 |
|---|---|---|---|---|
| Threshold >= 0.30 (overlapping) | 48 | 1.77 | **-0.001** | **0.583** |
| Fuzzy c-means (overlapping) | 20 | 9.15 | -0.039 | 0.383 |
| Spectral (disjoint) | 20 | 1.00 | -0.011 | 0.530 |
| *(real answer)* | *20* | *1.88* | *1.000* | *1.000* |

The two metrics disagree, and the disagreement is the finding. F1 says individual
groups are matched moderately well; **omega near zero says the pairwise overlap
structure is not captured at all**.

That does not contradict finding 3 above. *Members of a real group resemble each
other* is proven; *clustering on effectiveness recovers the groups* is not. The
likely cause: we cluster across all 770 branches, while EirGrid define each group
against **one specific overload on one specific circuit**. Averaging over every
branch dilutes the defining signal - and threshold, the only method that works one
constraint at a time, scores best.

**Next experiment, not run here because it edges into decision D1:** restrict the
effectiveness vectors to the ~40 circuits the WDT document actually names, rather
than all 770.

### 8. [scripts/contracted_pipeline.py](scripts/contracted_pipeline.py) → [script-output/contracted-pipeline-vs-constraints.csv](script-output/contracted-pipeline-vs-constraints.csv)
**Is new wind being connected where the network is already tight?**

Parses EirGrid's contracted-but-not-yet-generating wind farms and cross-references
their connection nodes against existing constraint groups.

| | |
|---|---|
| Contracted farms | 24 (all parsed, none dropped) |
| Total contracted capacity | **1,551 MW** — 36% of the existing fleet |
| Landing on a node already inside a constraint group | 4 farms, 233 MW (15%) |

The largest: **Carrownagowan 91 MW at Ardnacrusha** (three groups), **Drumnahough
72 MW at Lenalea** (three groups), **Moanvane 56 MW at Mount Lucas**.

Treat the 15% as a floor, not a finding: the WDT document only names stations for
the 99 it covers, so a pipeline node absent from that list is *unclassified*, not
proven unconstrained.

---

## What this folder establishes, in one paragraph

The two group mappings never contradict each other, so both can be trusted; the
gap is 16 South-East farms the model omits. The groups cannot be recovered from
weather, because they contain no weather information beyond proximity — so
network topology is the only route to them. And attributing curtailment without
topology gives a nearly uniform answer we can demonstrate is wrong. Every line
of evidence pointed at line-flow sensitivity, and computing it closes the loop:
11 of 12 real groups are electrically coherent against 1 of 12 for weather.
**EirGrid's stated method is confirmed from public data alone.**

---

## Running it

In order; each depends on the ones before.

```bash
python 08-analysis/scripts/audit_join.py
python 08-analysis/scripts/wind_by_bus.py
python 08-analysis/scripts/groups_vs_weather.py
python 08-analysis/scripts/curtailment_per_farm.py
python 08-analysis/scripts/contracted_pipeline.py
```

---

## References

Every file here is **generated**. Sources are the folders it draws from:

| Script | Inputs |
|---|---|
| `scripts/audit_join.py` | [../03-network/script-output/farm-to-constraint-group-map.csv](../03-network/script-output/farm-to-constraint-group-map.csv) |
| `scripts/wind_by_bus.py` | [../03-network/script-output/farm-to-constraint-group-map.csv](../03-network/script-output/farm-to-constraint-group-map.csv), [../04-meteorology/](../04-meteorology/) wind matrices |
| `scripts/groups_vs_weather.py` | [../04-meteorology/](../04-meteorology/) wind + farm locations, [../03-network/script-output/farm-to-constraint-group-map.csv](../03-network/script-output/farm-to-constraint-group-map.csv) |
| `scripts/curtailment_per_farm.py` | [../02-curtailment/script-output/system-state-15min-2026.csv](../02-curtailment/script-output/system-state-15min-2026.csv) (EirGrid measured), ERA5 via [../04-meteorology/scripts/wind_power.py](../04-meteorology/scripts/wind_power.py) |
| `scripts/contracted_pipeline.py` | [../04-meteorology/data](../04-meteorology/data) EirGrid contracted list, [../03-network/script-output/constraint-groups-to-stations.csv](../03-network/script-output/constraint-groups-to-stations.csv) |

Underlying licences are recorded in each source folder's own README: the network
model and SEAI farm list are CC BY 4.0, ERA5 via Open-Meteo is CC BY 4.0, and the
EirGrid reports are free to download.

**Method note.** The null-model approach in `scripts/groups_vs_weather.py` — measure
across a partition, then compare against a null holding the uninteresting
variable fixed — is taken from Session 2 of the graph workshop
([../05-workshops/](../05-workshops/)).
