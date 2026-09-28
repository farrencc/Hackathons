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
