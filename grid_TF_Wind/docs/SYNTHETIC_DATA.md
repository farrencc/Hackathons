# Synthetic profiles: what is real and what is fabricated

`synthetic.py` generates a deterministic hourly year for a TYTFS case without
touching the network. It exists for two different reasons — insurance against
[Phase 4's blocked hosts](PHASE4_PROFILES.md), and counterfactual scenarios
that no reanalysis year contains — and it is not a substitute for ERA5 where
ERA5 is available.

```bash
python synthetic.py build   --case <raw> --year 2030 --seed 42
python synthetic.py check   --case <raw>     # correlation against distance
python synthetic.py binding --case <raw>     # does WP2033 actually bind?
```

---

## 1. The line, drawn plainly

### Real — measured, published, or read out of a file

| what | where from |
|---|---|
| The network: buses, circuits, impedances, ratings, transformers | TYTFS PSS/E v35, via `psse.py` and `pypsa_net.py` |
| Which generators exist, what they are, where they connect, their `PT` | the TYTFS generator register |
| Which buses have load and **how much of the island's demand each one carries** | the TYTFS load records, `STAT = 1` |
| Site coordinates | OpenStreetMap, via `geocode.py` (Phase 2) |
| The four anchor states — demand totals and per-carrier capacity factors | computed from the four cases, `case_state()` |
| The wind power curve and the PV panel model | shared with `profiles.py`; the ERA5 path and this one use the same code |

### Fabricated — invented by this module, with a seed

| what | how |
|---|---|
| **Every hour of weather** — wind speed, clearness, temperature | correlated Gaussian random fields |
| The demand **time** shape | a stated winter-weekday curve, seasonal sinusoid, weekend factor, AR(1) day-to-day wobble |
| The hydro and thermal shapes | seasonal baseload with an evening boost; a residual-load envelope |
| Where in the year the anchors sit | 17 January 18:00 and 9 July 05:00, chosen |

### Chosen parameters — not fitted to anything, and the first things to change

| parameter | value | what it controls |
|---|---|---|
| `WIND_CORRELATION_KM` | 400 | how fast wind decorrelates with distance |
| `WIND_TIMESCALE_H` | 36 | how long a calm or a storm lasts |
| `CLOUD_CORRELATION_KM` / `CLOUD_TIMESCALE_H` | 150 / 6 | the same for cloud, which is smaller and faster |
| `TEMPERATURE_CORRELATION_KM` / `_TIMESCALE_H` | 600 / 72 | the same for temperature, which is bigger and slower |
| `WEIBULL_K` | 2.0 | the Rayleigh case, the usual first approximation |
| `TARGET_WIND_LOAD_FACTOR` | 0.30 | the annual fleet load factor the Weibull scale is solved for |
| `WIND_SEASONAL_AMPLITUDE` | 0.22 | winter windier than summer |
| `DEMAND_SEASONAL_AMPLITUDE` | 0.20 | winter demand higher than summer |

### Solved, not chosen

Two numbers are found by the module rather than picked, so that changing an
assumption changes them rather than silently changing the answer:

- **The Weibull scale**, by bisection against the same power curve `profiles.py`
  uses, so that the fleet load factor comes out at `TARGET_WIND_LOAD_FACTOR`.
  For the default settings it is **8.40 m/s**.
- **The demand affine scaling**, so that the year's maximum and minimum are
  the case vintage's own WP and SV totals.

> **The honest summary.** The *network*, the *fleet*, and *where the demand
> is* are real. *When* anything happens is invented. A number computed from
> this — a dispatch-down total, a constraint hour count — is a statement about
> a plausible year, not about any year that occurred. Where Phase 4's ERA5
> path can run, run that instead and use this to perturb it.

---

## 2. The one detail that would make it useless

**Wind is a spatially correlated field, not independent noise per bus.**

Independent noise passes almost every test you would write. The profiles would
be in [0, 1], the load factor would be 30%, each bus would look plausible on
its own. And it would be worthless, because 400 independent sites average out:
the central limit theorem flattens the fleet into a nearly constant series, and
a network that is never asked to carry a surge is never constrained.

Real calms and real storm fronts are hundreds of kilometres across. Donegal's
farms are at rated output in the same hours and at zero in the same hours, and
that is what loads the Letterkenny–Strabane tie.

So: a Gaussian random field with `ρ(d) = (1 − nugget)·exp(−d / 400 km)`,
driven through an Ornstein–Uhlenbeck process with a 36-hour synoptic
timescale, mapped onto a Weibull wind speed by a Gaussian copula, and put
through the same power curve as the ERA5 path.

### The check, measured from the output itself

`python synthetic.py check`

| distance | pairs | measured ρ | target exp(−d/400) |
|---|---|---|---|
| 0–25 km | 127 | **0.930** | 0.969 |
| 25–50 km | 353 | 0.877 | 0.911 |
| 50–100 km | 999 | 0.787 | 0.829 |
| 100–150 km | 1,113 | 0.691 | 0.732 |
| 150–200 km | 1,055 | 0.609 | 0.646 |
| 200–300 km | 1,511 | 0.507 | 0.535 |
| 300–400 km | 503 | 0.398 | 0.417 |
| 400–600 km | 10 | **0.307** | 0.287 |

Measured on the *output capacity factors*, not on the latent field, so it
includes everything the copula and the power curve do to the correlation. It
runs a little below target in the middle, which is the expected consequence of
a monotone non-linear map, and it decays — which is the property that matters.

### The other half: the aggregate has to move

| | |
|---|---|
| fleet mean | 0.313 |
| standard deviation | **0.248** |
| 5th / 95th percentile | 0.023 / 0.809 |
| hours below 5% | **1,053** (12% of the year) |
| hours above 80% | **486** |
| longest continuous calm | **112 hours** (4.7 days) |

That is a duration curve. Independent noise would give a standard deviation of
a couple of points and never approach either rail. Two tests assert both
halves, and either would fail if the correlation were removed.

---

## 3. Anchoring on the TYTFS states

The four cases are two conditions: **WP** is a winter-peak weekday evening,
**SV** is a summer-valley night. They are placed at 17 January 18:00 and 9
July 05:00 of the generated year, and the year is made to pass through them.

Demand is affinely rescaled so its **annual maximum and minimum are the case
vintage's own WP and SV totals**, and both extremes are nudged onto the anchor
hours with a raised-cosine taper so they land there rather than wherever the
noise left them. Wind and hydro capacity factors are tapered onto the case's
own values over ±18 hours.

Each vintage spans its own pair — WP2024's year runs 3,402 to 7,325 MW and
WP2033's runs 4,111 to 8,792 MW. Taking the peak from whichever case is
largest would put 2033's demand into 2024's year.

| case | anchor | demand | wind cf | hydro cf |
|---|---|---|---|---|
| WP2024 | 17 Jan 18:00 | 7,324.5 = 7,324.5 ✓ | 0.0000 = 0.0000 ✓ | 0.9434 = 0.9434 ✓ |
| SV2024 | 9 Jul 05:00 | 3,402.3 = 3,402.3 ✓ | 0.0000 ✓ | 0.0000 ✓ |
| WP2033 | 17 Jan 18:00 | 8,791.8 = 8,791.8 ✓ | 0.0995 = 0.0995 ✓ | 0.6812 = 0.6812 ✓ |
| SV2033 | 9 Jul 05:00 | 4,111.1 = 4,111.1 ✓ | 0.0000 ✓ | 0.4962 ✓ |

### The anchor that is deliberately not applied

**WP2033 dispatches 373 MW of solar, a capacity factor of 0.100, at a
winter-peak evening. WP2024 dispatches 38 MW, 0.035.** At 18:00 on 17 January
the sun is well below the horizon at every Irish latitude, so neither is
reachable, and forcing it would put daylight in the profile at night.

This is not a bug in TYTFS. **A TYTFS case is a security state, not a
timestamped instant** — a set of conditions the network must withstand, with
each carrier's output chosen for the study rather than for a clock. The
generator refuses that anchor, records why in `anchor_report`, and leaves the
solar profile to the sun:

```
case                  carrier  target_cf  achievable_cf  note
TYTFS2024_WP2033_V35  wind        0.0995         0.8707  applied
TYTFS2024_WP2033_V35  solar       0.1000         0.0000  not applied: the case's
                                                         value is unreachable at
                                                         this hour of this date
```

The same reasoning cuts the other way and is worth being explicit about: the
wind anchor **is** applied, so 17 January evening in the generated year is
calm because the case says so. That is a security assumption being written
into one hour of the weather. It is confined to a ±18-hour window on purpose —
a year in which every cold evening was calm would be a worse lie than the one
this module replaces, and Irish winter peaks frequently coincide with high
wind.

---

## 4. The shapes

**Demand.** A stated winter-weekday curve, normalised so the peak hour is 1.0:

```
00-05  0.72 0.69 0.67 0.66 0.66 0.68     overnight trough
06-11  0.74 0.83 0.90 0.92 0.92 0.91     morning ramp
12-17  0.90 0.89 0.88 0.89 0.94 1.00     midday plateau, evening rise
18-23  1.00 0.96 0.91 0.86 0.81 0.76     evening peak 17:30-18:30, then fall
```

times a seasonal sinusoid (±20%), times 0.88 at weekends, times an AR(1)
day-to-day wobble of 3% for weather and holidays. Then allocated across the
TYTFS load records **in proportion to each record's own `PL`**, using
`profiles.allocate_demand`, so the spatial pattern is the TSO's and only the
temporal shape is invented. Row sums preserve the island total exactly.

**Hydro.** Steady seasonal baseload between the vintage's WP and SV capacity
factors, with a 25% evening boost at 17:00–20:00 — run-of-river with a small
reservoir held for the peak.

**Thermal.** A residual-load envelope: `demand/max(demand) − 0.6 × fleet wind
cf`, rescaled to [0.15, 1.0]. It rises with demand and backs off when wind is
high, as asked.

> **A caveat on the two dispatchable shapes.** These are **availability
> envelopes, not dispatch**. In an optimisation the solver decides, and a
> study running LOPF should set thermal `p_max_pu` to 1 and let it — which is
> what `binding()` does, and what made the difference between an infeasible
> problem and a working one. Imposing an envelope as an upper bound on a
> machine that also carries a must-run lower bound is how that study failed
> the first time it was run.

---

## 5. Does WP2033 actually bind?

The requirement the exercise turns on. WP2033 has **32.1 GW of registered
capacity against 9.0 GW of dispatch — 72% headroom**. If the generated
profiles do not produce hours where the network cannot take what the wind is
offering, the central problem does not appear.

`python synthetic.py binding` runs the case's own transmission network over
the windiest hours of the generated year, with renewables offered at a
negative price so the optimisation maximises their output subject to the
network and nothing else. Dispatch-down is then available minus dispatched.
Over the windiest hours of a case with 72% headroom it is a mix of
constraint-based dispatch-down (stranded behind a binding circuit) and
surplus-based (more wind than the demand can absorb); the binding-circuit
counts beside it are what say the network is doing some of the work.

None of it is curtailment in the SEM/EirGrid sense — that is a system-wide,
pro-rata reduction ordered against an SNSP or an inertia limit, and there is
no SNSP constraint, no inertia constraint and no unit commitment anywhere in
this model.

### It binds

| | WP2024 | **WP2033** |
|---|---|---|
| hours studied (windiest) | 60 | 60 |
| energy offered | 1.4 GWh | **342.8 GWh** |
| energy dispatched down | **0.0 GWh** | **20.4 GWh** |
| dispatch-down | 0.0% | **5.94%** |
| hours with dispatch-down | 0 of 60 | **60 of 60** |
| worst circuit loading | 1.000 | 1.000 |

Over 120 hours the WP2033 figure is 40.1 GWh dispatched down of 681.9 GWh
offered, **5.89%**, with dispatch-down in every hour.

The 2024 contrast is not a fair fight and should not be read as one: the
WP2024 *network* is built from in-service machines and that case runs almost
no wind, so there are only 1.4 GWh to hold back. What it does show is that the
scenario, not the profile generator, is what creates the problem.

### And it binds where Phase 3 said it would

The single binding circuit, at 1.000× in every hour, is **`3581-89516-1` —
Letterkenny to Strabane**, the 93 MVA 110 kV tie into Northern Ireland.

[Phase 3](PHASE3_NORTHWEST.md) §7 found that circuit binds first, at about
29% fleet capacity factor, from a completely different method: a DC power flow
on the 2024 network with every other boundary tie pinned at the case's own
values. A full LOPF over synthetic correlated weather on the 2033 network
finds the same circuit. Two methods that share no code beyond the network
agree on the answer, which is worth more than either on its own.

The ten most dispatched-down generators are all in the North-West:

| generator | bus | MWh dispatched down over 120 h |
|---|---|---|
| 40771-1 | Meentycat | 5,626 |
| 40971-1 | Mulreavy | 4,956 |
| 49971-1 | Sorne Hill | 3,259 |
| 35971-1 | Lenalea | 3,216 |
| 68402-1 | | 3,170 |
| 40772-2 | Meentycat 2 | 1,921 |
| 68260-1 | Cronalaght | 1,784 |
| 35875-1 | Cark | 1,573 |

**One caveat, stated because it is load-bearing.** Only one circuit binds.
The model prices export to Northern Ireland at nothing beyond that tie's
thermal limit, and in reality SONI would redispatch around it. A study that
cares about the absolute dispatch-down number should model the Northern Ireland
side rather than treating it as an infinite sink behind a 93 MVA wire. What
the result establishes is that the profiles *do* produce binding constraints
and where, not that 5.9% is the right number.

---

## 6. Determinism

Seeded with **42**, matching the convention in `nodes_24hr.xlsx`'s own README.
The same seed gives a bit-identical year; a different seed gives a different
year that still passes through the same anchors. Both are asserted.

Seeds are used in two independent streams — one for the Weibull scale search,
one for the fields — so changing the target load factor does not reshuffle the
weather.

---

## 7. Building counterfactuals

The parameters in §1 are the knobs, and they are arguments rather than edits:

| scenario | how |
|---|---|
| a worse wind year | `TARGET_WIND_LOAD_FACTOR` down to 0.25 |
| a stormier one | `WIND_SEASONAL_AMPLITUDE` up, `WIND_TIMESCALE_H` down |
| less spatial diversity — a harder network problem | `WIND_CORRELATION_KM` up to 800 |
| more diversity | down to 150 |
| demand growth | scale the two anchor demands before calling `demand_series` |
| a different build-out | use a different case, or edit the register |
| a different sample of the same climate | `--seed` |

`WIND_CORRELATION_KM` is the interesting one for a network study. Raising it
makes every site rise and fall together, which is the worst case for
constraint; lowering it lets the fleet smooth itself. Both are physically
possible for particular weather regimes, and the difference in dispatch-down
between them is a result worth having.

---

## 8. What this is not

- **Not a forecast, and not a historical record.** One arbitrarily sampled
  synthetic year.
- **Not validated against anything.** [Phase 4](PHASE4_PROFILES.md) §5 has a
  validation harness that compares a modelled fleet against EirGrid's
  published wind series; it applies to the ERA5 path and there is nothing here
  for it to check. A synthetic year has the right statistics because it was
  built to have them.
- **Not a replacement for ERA5.** The correlation structure here is an
  exponential decay with a chosen length scale. The real thing is anisotropic,
  non-stationary, and shaped by the actual track of actual depressions. Where
  both are available, use ERA5 and use this to perturb it.
- **Not spatially resolved below the ERA5-Land cell**, because sites sharing a
  cell share coordinates from Phase 2's geocoding, and 82 of WP2033's
  generator records — 7.8 GW, almost all of it offshore — have no coordinate
  at all and therefore no profile.
