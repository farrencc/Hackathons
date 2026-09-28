# The dispatch ensemble: SNSP vs. dP/H_COI as predictors of frequency security

`ensemble.py`, `inertia.py`, `frequency.py`, `compare.py` and `validate.py`
build a population of committed all-island dispatch states, trip each one, and
ask which of two numbers better predicts what happens next: **SNSP**, the
limit EirGrid dispatches to, or **f₀·ΔP / 2E**, initial RoCoF from the swing
equation.

```bash
python ensemble.py time                       # one scenario, timed
python ensemble.py run --n 50                 # the smoke-test ensemble
python scripts/run_ensemble.py --n 1000       # a real run, launched by hand
python compare.py                             # metrics and figures
python validate.py                            # realism check, if data allows
```

---

## 0. Environment as built

**Read this before any number below.** It says which parts of the pipeline
ran on real inputs and which on stand-ins.

| input | path taken | what that means |
|---|---|---|
| **Network** | **Real.** TYTFS 2024 PSS/E v35 cases are in the clone at `data/TYTFS2024_studyfiles/`, read with `psse.read_raw()` and converted with `pypsa_net.build()` | Topology, ratings and the generator register (PT, PB, MBASE) are EirGrid's. `testcase.py` was not needed and was not written. |
| **Weather** | **Synthetic.** `synthetic.py` | Open-Meteo refused at the proxy (see below). Wind and solar are spatially correlated random fields anchored on the TYTFS states: *when* anything happens is invented. |
| **Validation** | **Fixture only — not a validation.** `validate.py` against a committed *format* fixture | The Smart Grid Dashboard is refused at the proxy. The fixture exercises the code and is labelled as synthetic in every row; it is **not** historical data and no conclusion about realism is drawn from it. The live check skips with a message. |

### The two network probes

One request each, inside a `try/except`, at the start of the session:

```
archive-api.open-meteo.com   ProxyError: Tunnel connection failed: 403 Forbidden
www.smartgriddashboard.com   ProxyError: Tunnel connection failed: 403 Forbidden
```

A 403 at CONNECT is an egress-policy denial, the same one
[Phase 4](PHASE4_PROFILES.md) §0 recorded. It was not retried and no mirror
was looked for.

### Dependencies

Installed with pip into the system interpreter (Python 3.11.15):

| package | version |
|---|---|
| pypsa | 1.3.0 |
| linopy | 0.9.1 |
| highspy | 1.15.1 |
| pandas | 3.0.6 |
| numpy | 2.4.6 |
| scipy | 1.17.1 |
| pyarrow | 25.0.1 |
| matplotlib | 3.11.2 |
| pytest | 9.1.1 |

HiGHS is the only solver. Nothing here calls, or has a code path for, a
commercial one. The container has 4 CPUs; the solver is run single-threaded
so that timings are comparable and a parallel ensemble run is one process per
core.

---

## 1. Network and dispatch

### Cluster the network, not the generators

The 646-bus transmission model (`pypsa_net.build`, 110 kV floor) is clustered
geographically — seeded k-means on the geocoded bus positions, **within each
jurisdiction** so no node straddles the border — to **32 IE + 8 NI = 40 AC
nodes**, plus the three HVDC far terminals kept as nodes of their own. Every
line and transformer between two clusters is kept at its system per-unit
reactance and combined in parallel with the others between the same pair;
branches inside a cluster vanish. That is what geographic clustering does to
a DC model and no more. The flows are indicative; they are not what this study
measures.

**Generators are not aggregated.** H_COI depends on *which* machines are
synchronised and ΔP on the largest single one online; a 1,300 MW "Moneypoint"
block would get both wrong. Each unit is its own committable generator, on
the cluster its own PSS/E bus maps to. The one merge is a **multi-shaft
CCGT** — Huntstown 1, Tynagh, Poolbeg, Coolkeeragh, Ballylumford C — whose gas
and steam turbines are separate generator records but one plant that trips as
one. Its `p_nom` is the sum of PT and its MVA the sum of MBASE, so its kinetic
energy is exactly its machines'.

Wind and solar, neither committable nor synchronous, are aggregated per
cluster.

### The fleet is the register, not the case's dispatch

The WP2024 case runs 43 of its machines; the register lists every record,
switched in or out. The optimiser gets the whole register, because a unit the
winter-peak study left off is still a unit that can be committed on a summer
night.

The raw format carries no fuel type, so the technology of each large unit is
**read off its PSS/E bus name** — `STATION_TECHNOLOGY` in `ensemble.py`. That
is a reading of which station is which, checked against the case's PT, PB and
MBASE; it is not in the file.

| technology | modules | MW |
|---|---|---|
| CCGT | 10 | 4,293 |
| OCGT (incl. TEG, flex gas, peakers) | 45 | 3,172 |
| steam (Moneypoint coal, Edenderry, waste, biomass) | 10 | 976 |
| hydro | 11 | 197 |
| pumped storage (Turlough Hill, as 4 storage units) | 4 | 292 |

Left out, and why:

| records | MW | reason |
|---|---|---|
| batteries (24) | 1,124 | non-synchronous; represented by the exogenous FFR volume in `frequency.py` |
| Moneypoint 2's condenser record (`ID = SC`) | 0 | the same machine as MNYPG2; the condenser fleet is sampled separately |
| STATCOMs, SVCs | 0 | no active power |
| records under 10 MW | 70 | embedded CHP and biogas; 32 MW of them in service in WP2024 |

Two corrections to the existing carrier map, made locally rather than in
`pypsa_net.carrier_of` so that nothing already built changes: `BS_HUNTSTOWN`
ID 2 is Huntstown 2, a 400 MW CCGT, not biomass; and the NI renewables on
`WIND_*` and `RENEW_*` buses are wind.

### Committable, with the constraints that make commitment matter

Every conventional unit: `committable=True`, and from the technology table
in `ensemble.py`: `p_min_pu`, `min_up_time`, `min_down_time`,
`ramp_limit_up/down`, `start_up_cost` and a marginal cost. **None of these is
in the TYTFS file**; they are typical of each plant type and exist to put the
merit order and the commitment dynamics in the right order.

A single snapshot cannot express a minimum up time, so each scenario solves a
**24-hour window** and is read off hour 17 of it. Every unit starts the
window cold and free to start; seventeen hours of lead-in keep that from
showing at the target hour.

### What is constrained, and what deliberately is not

> **SNSP, inertia and RoCoF are not constrained.** They are the outcomes this
> study measures. An SNSP ≤ 75% or inertia ≥ 23,000 MWs constraint would stop
> the ensemble reaching the insecure region and cut the interesting half off
> every scatter by construction. The code says so where a helpful reader
> would otherwise add one, and `test_no_security_metric_is_constrained` fails
> if one appears.

What is enforced:

- **Minimum units online**, from the Operational Constraints Update: at least
  5 large conventional units on load in Ireland and 3 in Northern Ireland
  (`MIN_UNITS_RULE = "split"`), or the relaxed all-island 7. "Large" is a
  thermal module of 100 MW or more. This is a real floor under H_COI.
- **Interconnectors** pinned at a sampled setpoint within EWIC −526 to
  +504 MW and Moyle −400 to +442 MW. Greenlink is out for 2024 (STAT = 0 in
  the case; commissioned 2025).
- **Primary reserve cover**: for every committed unit, the POR held by the
  *other* units covers 75% of what it is producing, and likewise for the
  largest interconnector import. A unit's POR is bounded by its headroom and
  a per-technology capability; a pumping Turlough Hill unit can offer its pump
  load. A shortfall is penalised rather than infeasible, and recorded.

### Runtime

One scenario (`python ensemble.py time`, winter-peak hour 400, 7.3 GW):

| | |
|---|---|
| nodes | 43 (40 AC + 3 HVDC terminals) |
| committable units / storage units | 76 / 4 |
| snapshots | 24 |
| build (read case, cluster, synthetic year) | 8.6 s, once per run |
| **single solve, wall-clock** | **8.0 s** (HiGHS single-thread, 0.5% MIP gap) |

Well inside the 60 s budget, so no further clustering or fleet reduction was
needed. Written to `docs/ensemble_timing.json`. A windy summer night solves
in about the same time and runs exactly at the minimum-units floor: eight
units, roughly 13,000 MWs — the insecure region is reachable without anything
pushing it there.

---

## 2. Inertia and the contingency

### The largest assumption in the study

**The inertia constants are assumed, not measured.** A `.raw` file is a load
flow: it gives each machine's MVA (`MBASE`) and nothing about its rotor.
Inertia constants live in `.dyr` dynamics files, which EirGrid does not
publish. Every H below is a typical value for the technology, applied to
every machine of that technology. The system kinetic energy that the whole
comparison turns on is only as good as this table:

| technology | H (s, on MBASE) | constant |
|---|---|---|
| CCGT | 6.0 | `inertia.H_SECONDS` |
| OCGT | 4.5 | |
| coal / peat steam | 4.0 | |
| hydro | 3.0 | |
| pumped storage | 3.0 | |
| synchronous condenser | **2,000 MWs per unit, chosen** | `inertia.SYNC_CONDENSER_MWS` |

`inertia.py` holds the only inertia numbers in the codebase, and
`test_no_other_module_carries_an_inertia_number` fails if a second file
grows one. The condenser figure is a representative large condenser with a
flywheel, not a published LCIS number; the sampler draws 0 to 6 of them.

### What is computed

```
E        = Σ_i H_i · S_i  (synchronised machines, S = MBASE)  + n_SC · 2,000 MWs
df/dt|₀₊ = f₀ · ΔP / (2E),   f₀ = 50 Hz
```

Wind, solar, batteries and HVDC contribute nothing. At the 23,000 MWs floor,
500 MW gives **0.543 Hz/s** — asserted to ±0.001 in `test_inertia.py`.

> The brief's 0.5 Hz/s limit is the pre-DS3 one. `papers/MPID229a` records
> that EirGrid now operates to **1 Hz/s measured over 500 ms**, against which
> the 23,000 MWs floor is conservative. Both thresholds are reported in §5.

### ΔP is the reference incident, per scenario

`RI⁺ = LSI + C_loss`, with LSI the largest of any **committed synchronous
module's dispatched output** and any **interconnector's import** at the
island end — per the SOGL definition, a single generating module or single
HVDC interconnector. A multi-shaft CCGT is one module and trips whole; Moyle
is one interconnector (both poles). `C_LOSS_FRACTION` defaults to 0. RI⁻ —
the largest export or single pump load — is recorded but not simulated.

The ~500 MW today / ~700 MW with Celtic / ~7.5 GW peak figures are
plausibility bounds in tests, never the value.

### Post-trip inertia

A tripping unit takes its rotor with it, `E_post = E_pre − H_trip·S_trip`; an
HVDC import takes none. The incident type is kept in every scenario record so
the comparison can be split on it.

---

## 3. The sampling design

The ensemble is over **dispatch states**. ΔP is derived from each solved
state, never sampled, so both predictors are functions of system state and
neither sees an input the other cannot.

A seeded Latin hypercube (`scipy.stats.qmc`, seed 42) over:

| dimension | range | how |
|---|---|---|
| weather | hour of the synthetic 2024 year | spatially correlated wind and solar per cluster from `synthetic.py`, and the window's demand *shape* |
| demand level | 3,402–7,325 MW | the 2024 vintage's own SV and WP totals; the window is rescaled so its target hour sits at the draw |
| EWIC, Moyle | −526…+504, −400…+442 MW | pinned over the window, both directions |
| condensers | 0–6 × 2,000 MWs | `inertia.LCIS_UNITS` |
| forced outages | one dimension per large unit | out if its draw < `FORCED_OUTAGE_RATE` = 10% |

An outage draw that would leave a jurisdiction unable to meet the
minimum-units rule is partly undone — the least-extreme draws come back first
— and that is recorded (`outages_restored`, 5 of 50 scenarios). A state the
real system cannot be put in is not a state worth sampling.

**Default ensemble: 50 scenarios, a smoke test and not a result.** It runs
the pipeline end to end inside one session (205 s on 4 workers). For a real
run, `scripts/run_ensemble.py --n 1000` (~35 min on 4 cores).

### SNSP, EirGrid's way

```
SNSP = (wind + solar + net interconnector imports)
       / (demand + pump-storage pumping load + net interconnector exports)
```

Not wind/demand. `test_snsp_hand_worked_with_pumping` pins it on a worked
case: (2000 + 100 + 200) / (4000 + 200) = 0.5476.

### The record

`data/ensemble/<vintage>_seed<seed>_n<n>/` (gitignored), one parquet part per
scenario per table, written as each scenario is solved — a stopped run is a
usable partial ensemble, and re-running resumes it.

| table | one row per | carries |
|---|---|---|
| `scenarios/` | scenario | the LHS coordinates and seed, demand, pump load, wind/solar dispatched and available, flows, SNSP, units online, E pre/post with machine and condenser parts, LSI, RI⁺ and RI⁻ with element and type, H and MVA of the tripped unit, POR scheduled/available and SOR available, shortfall, shed, solve status and time |
| `units/` | scenario × module | technology, jurisdiction, cluster bus, p_nom, MBASE, dispatch, online, forced-out, H, E component |
| `buses/` | scenario × node | net injection |

Enough to recompute every predictor and outcome without re-solving;
`test_record_is_enough_to_recompute_inertia` rebuilds E from the unit rows.
POR *available* is what the machines still spinning after the trip can give
from their headroom, capped per technology; a pumping Turlough Hill unit gives
its pump load. That, not the scheduled figure, is what `frequency.py` uses.

### What the 50-scenario ensemble contains

| | min | median | max |
|---|---|---|---|
| SNSP | 0.045 | 0.424 | **0.860** |
| E pre-trip, MWs | **19,296** | 35,830 | 59,654 |
| LSI, MW | 188 | 468 | 501 |
| units online | 8 | 21.5 | 62 |

- 9 scenarios above 75% SNSP, 6 below 23,000 MWs pre-trip (9 post-trip), 4
  both. No constraint leaked.
- LSI correlates with wind output at Spearman **−0.62**: windy states run
  units at minimum load and LSI falls.
- Incident: 41 unit trips (26 of them Ballylumford C, the largest module at
  487 MW), 9 HVDC.
- Every scenario solved optimal, with no load shed and no POR shortfall.
  Solve time under contention from 4 parallel workers: median 9.8 s, max
  41.8 s.
