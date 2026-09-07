# Phase 4: hourly profiles from ERA5, and the demand shape from EirGrid

`profiles.py` turns each TYTFS case's four snapshots into a year, by fetching
ERA5 through Open-Meteo's historical archive and converting it to a
`p_max_pu` per wind and solar generator. `test_profiles.py` guards it — 32
tests, all of which run without a network.

```bash
python profiles.py sites                              # what would be requested
python profiles.py fetch    --year 2023               # ERA5 -> data/raw/weather/
python profiles.py build    --year 2023               # -> data/profiles/
python profiles.py validate --year 2023 --actual <eirgrid wind csv>
```

---

## 0. The blocker, first, because it is the whole difference between this and a finished job

**Both data sources are refused by this session's egress policy.** Not slow,
not rate-limited — refused at the CONNECT, before any request is made:

```
archive-api.open-meteo.com:443   gateway answered 403 to CONNECT
api.open-meteo.com:443           gateway answered 403 to CONNECT
www.smartgriddashboard.com:443   gateway answered 403 to CONNECT
smartgriddashboard.com:443       gateway answered 403 to CONNECT
cms.eirgrid.ie:443               gateway answered 403 to CONNECT
www.eirgrid.ie:443               gateway answered 403 to CONNECT
```

(from the agent proxy's own failure log; the same six hosts, six times, one
attempt each). A 403 at CONNECT is an organisation policy denial. I have not
retried it and I have not looked for a mirror, because routing around an
egress policy is not mine to do.

**So there are no profiles in this repository, and there is no validation
result.** What there is instead is the whole pipeline, tested, with the fetch
as the only untested step — and every path that cannot get real data raises
`profiles.Unavailable` rather than falling back to something invented. That
is deliberate and it is tested:

```
test_loading_a_cell_that_was_never_fetched_raises
test_a_partial_year_is_not_cached_as_a_complete_one
test_a_response_missing_a_variable_is_refused
test_an_unreadable_eirgrid_file_raises_rather_than_guessing
```

The brief is explicit that the validation is the only thing standing between a
real profile and a plausible-looking fabrication. Shipping a synthetic year
here, however carefully labelled, would be that fabrication. There isn't one.

**Two ways to finish it.** Allowlist `archive-api.open-meteo.com` and
`www.smartgriddashboard.com` and re-run the four commands above — total
traffic is about six HTTP requests per case-year. Or, if the policy is not
going to move: `python profiles.py fetch` is the only step that needs the
network, and `read_eirgrid()` already takes a CSV downloaded by hand, so
dropping the dashboard export into `data/raw/eirgrid/` and the Open-Meteo JSON
into `data/raw/weather/` makes everything else run unchanged.

---

## 1. What would be requested

One row per **generator record in the case's register**, not per dispatched
machine: a year of weather is for running the fleet, and the four published
cases run between 3% and 21% of it.

| case | wind and solar records | MW | with coordinates | 0.1° cells | requests/year |
|---|---|---|---|---|---|
| WP2024 | 421 | 7,346 | 389 (86% of MW) | 122 | **5** |
| WP2033 | 610 | 16,491 | 528 (53% of MW) | 146 | **6** |

Carrier comes from the bus-name convention Phase 2 established (`W_`, `PV_`);
coordinates from the station Phase 2 geocoded, resolved through the same
least-reactance aggregation the transmission network uses.

**Sites are deduplicated to the ERA5-Land grid.** Two farms in one 0.1° cell
get identical weather because ERA5-Land does not distinguish them — a cell is
about 10 km across. They therefore get identical profiles, and `p_max_pu`
says so rather than adding noise to make them look independent. Adding that
noise would destroy the one property the whole exercise is for.

That deduplication is also what makes the request count trivial: 146 cells at
25 locations per request is **six HTTP GETs for a year of the whole island**.
Rate limiting is not going to be the problem.

### The unplaced, and why it matters more in 2033

| case | records with no coordinate | MW |
|---|---|---|
| WP2024 | 32 | 1,038 |
| WP2033 | 82 | **7,770** |

WP2024's are the Phase 2 geocoding failures propagating through, traceably:
Croaghonagh (139 MW), Lickny, Derrybrien, Lislea, Knocknamona. WP2033's are
something else — **almost all of the missing 7.8 GW is offshore**: Dublin
Array 824 MW, Arklow Offshore 800, Codling 1/2/3 at 483 each, Kish/Bray 450,
Skerd Rocks 450, Oriel 370.

That is nearly half the 2033 wind fleet by capacity, and it needs its own
treatment rather than a geocoding fix:

- **The onshore substation is the wrong coordinate.** The weather at Codling
  Bank is not the weather at its landfall; the whole point of the exercise is
  spatial correlation, and putting an offshore farm at its cable terminus
  gets it wrong by 20 km and by a land–sea boundary.
- **ERA5-Land does not cover sea.** Offshore sites need `--model era5`
  (0.25°), which the module already supports.
- **The power curve is different.** Offshore machines are larger, hub heights
  are 120–150 m rather than 100, and the wind resource is less sheared.

Until those coordinates come from somewhere — the consent documents, or the
Marine Area Consent boundaries — the honest thing is that they have no
profile, which is what `unplaced()` reports.

---

## 2. The wind conversion, stated

Three steps. The third is the one that is usually skipped and it is the
largest.

### Hub height, from the two ERA5 levels

`wind_speed_10m` is not decoration. With `wind_speed_100m` it gives the local
power-law shear exponent, **hour by hour**:

```
alpha = ln(v100 / v10) / ln(100 / 10)
v_hub = v100 * (h / 100) ** alpha
```

Computed rather than assumed, because it is not a constant: it collapses
towards 0.1 in a well-mixed daytime boundary layer and rises past 0.4 in a
stable night-time one, and that diurnal swing is worth tens of percent at hub
height. Clipped to [0.05, 0.60] so a calm hour with a near-zero 10 m wind
cannot produce nonsense.

**The default hub height is 100 m, which makes the correction a no-op** —
`wind_speed_100m` is already at 100 m. PSS/E raw files have no hub heights.
For a modern Irish onshore farm the true figure is 80–100 m, so the correction
is small; give a site a real height and the shear exponent makes it exact.
`--hub-height` sets it.

### The turbine curve

A generic IEC Class II onshore machine:

| | |
|---|---|
| cut-in | **3.0 m/s** |
| rated | **12.0 m/s** |
| cut-out | **25.0 m/s** |

and between cut-in and rated, the cubic the aerodynamics give:

```
P(v) = (v³ − v_in³) / (v_rated³ − v_in³)
```

which is 0 at cut-in and 1 at rated by construction. Zero below cut-in, 1
between rated and cut-out, 0 above.

### The farm curve — the correction that matters

An ERA5 cell is 10 km across and a wind farm is tens of turbines spread over
it, so the single-turbine curve applied to a cell-mean wind speed is far too
sharp: it gives a farm that reaches rated output all at once and cuts out all
at once, and neither happens. The standard fix (Staffell & Pfenninger 2016) is
to convolve the turbine curve with a Gaussian, which is what a spread of wind
speeds across a farm does to it. **σ = 1.5 m/s** by default.

What that does to the curve:

| wind speed | turbine | farm (σ = 1.5) |
|---|---|---|
| 3 m/s (cut-in) | 0.000 | 0.017 |
| 6 m/s | 0.111 | 0.135 |
| 12 m/s (rated) | 1.000 | **0.870** |
| 25 m/s (cut-out) | 0.000 → | **0.493** |
| 28 m/s | 0.000 | 0.022 |

Half the farm is still running at nominal cut-out, and the fleet reaches only
87% of nameplate at nominal rated speed. Both are right and both matter for a
dispatch-down study.

Then **availability 0.90** — wake, array electrical, soiling, icing,
outages — applied as a flat multiplier.

`FARM_SPREAD` and `WIND_AVAILABILITY` are the two free parameters, and §5 is
about letting the validation set them rather than me.

---

## 3. The solar conversion, stated

Deliberately simple, as the brief allows, and every assumption written down.

| assumption | value | why |
|---|---|---|
| array | fixed tilt, no tracking | Irish utility solar is overwhelmingly fixed-tilt |
| tilt | 35° from horizontal | typical for the latitude |
| azimuth | 180°, due south | |
| sky diffuse | isotropic | at 53°N more than half the annual resource is diffuse, so the sky model matters more than any refinement left out |
| ground albedo | 0.20 | grass |
| NOCT | 45 °C | |
| power temp. coefficient | −0.004 /°C | |
| system losses | 14% | inverter, wiring, soiling, mismatch |
| clipping | to 1.0 | capacity is the inverter rating, so the clip stands in for an oversized array |

Solar position is NOAA's algorithm, accurate to a fraction of a degree — far
inside anything else in the model. It is checked against arithmetic that does
not need this module: at solar noon the zenith is |latitude − declination|,
and the tests assert that for Dublin at both solstices.

Plane-of-array irradiance:

```
DHI  = max(GHI − DNI·cos(zenith), 0)
POA  = DNI·cos(AOI) + DHI·(1 + cos β)/2 + GHI·ρ·(1 − cos β)/2
```

Panel:

```
T_cell = T_air + POA·(NOCT − 20)/800
P/P_STC = POA/1000 · (1 + γ·(T_cell − 25)) · (1 − losses),  clipped to [0, 1]
```

Not modelled, and each of these is a known omission rather than an oversight:
incidence-angle and spectral modifiers, row-to-row shading, snow, and
inverter part-load efficiency.

---

## 4. Demand

**The spatial allocation comes from the TSO's model and only the temporal
shape from the dashboard**, which is the brief and is also the only defensible
split: EirGrid publishes one number for the island, and TYTFS says where the
load is.

```
p_set[t, load i] = D_island(t) × PL_i / Σ PL
```

with the weights taken over **in-service** load records. That filter is not
cosmetic: 34 of WP2024's 266 load records are switched out and sit at buses
that already carry an in-service load, so weighting over the register would
double-count 34 buses and put 922 MW in the wrong places. (Phase 1 §4.)

The allocation preserves the island total exactly, row by row, which is
asserted by a test.

The dashboard's quarter-hours are averaged to the hour ERA5 is on.

---

## 5. The validation, which is the point

```
python profiles.py validate --year 2023 --actual data/raw/eirgrid/wind_ALL_2023.csv
```

Sum the modelled fleet, scale by capacity, compare with EirGrid's published
all-island wind generation. It reports:

| number | what it tells you |
|---|---|
| `correlation`, `r2` | whether the **timing** is right — whether the calms and the storms fall in the same hours. This is what ERA5 buys and what a random walk cannot have at all. |
| `mae_mw`, `mae_pct_of_capacity` | the headline error, in units that mean something |
| `bias_mw`, `modelled_load_factor` vs `actual_load_factor` | whether the **level** is right |
| `rmse_mw` | |

**How to read the result.** The two failure modes are independent and the
report separates them deliberately:

- **Correlation low (below ~0.85) with the level about right.** The power
  curve is not the problem. Something is wrong with *where the sites are* —
  missing capacity, wrong coordinates, or the offshore fleet placed at its
  landfall. Look at `unplaced()` first.
- **Correlation high (0.9+) with the load factor several points off.** The
  timing is right and the level is not, which is exactly what the two free
  parameters are for. `calibrate()` sweeps `FARM_SPREAD` × `WIND_AVAILABILITY`
  and reports correlation, MAE and bias for each — and the informative thing
  about that sweep is that the correlation barely moves across it while the
  bias moves a great deal. The timing comes from ERA5; only the level is being
  fitted, and fitting a level against a published series is calibration rather
  than curve-fitting.

**A sense check to apply before believing any of it.** Ireland's annual
onshore wind load factor is in the high twenties to low thirties percent. If
the modelled capacity-weighted load factor lands far outside that, the curve
or the availability is wrong regardless of what the correlation says — and the
same figure can be computed from the dashboard series directly, so it is
checkable against the same download rather than against my memory.

**One caveat that will bite.** The modelled fleet is the TYTFS *register* for
a scenario year, and the dashboard's actuals are the fleet that was
physically connected in the year of weather requested. Those are not the same
capacity. For WP2024 against a recent year they are close; for WP2033 against
any year of real weather they are not, and the comparison should be made on
**load factor**, not MW. `validate_wind` reports both, which is why.

---

## 6. What is where

| path | what |
|---|---|
| `profiles.py` | the pipeline |
| `test_profiles.py` | 32 tests, none needing a network |
| `data/raw/weather/<model>_<year>_<cell>.json` | the cache, one file per cell-year, never re-fetched (gitignored) |
| `data/raw/eirgrid/<area>_<region>_<year>.json` | the dashboard series (gitignored) |
| `data/profiles/<case>_<year>_p_max_pu.csv` | the output, wide, snapshot index (gitignored — an hour-year is ~50 MB) |
| `data/profiles/<case>_<year>_sites.csv` | every generator, its cell, its coordinate, and whether it got a profile |
| `data/profiles/<case>_<year>_load_factors.csv` | per-generator annual load factor, the first thing to look at |

Caching is per cell-year and is checked before every request, so re-running
`fetch` after a partial run costs nothing and asks for nothing twice. A
response is written to the cache only after it has parsed and been checked for
a full year of all five variables — a half-written year cannot be mistaken for
a complete one.

---

## 7. Still open

- **The fetch, which needs the two hosts allowlisted.** Six requests per
  case-year.
- **Offshore coordinates.** 7.8 GW of the 2033 fleet, and the onshore
  substation is the wrong answer for it. Needs real site coordinates and
  `--model era5`.
- **Hub heights.** All defaulted to 100 m, which makes the correction a no-op.
  A per-site table would improve the level, though not the timing.
- **The calibration itself**, which cannot be run until there is something to
  calibrate against.
