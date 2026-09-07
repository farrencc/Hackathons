# 04 — Meteorology

Where the wind is, how hard it blows, and how much power that makes.

This is the layer that connects weather to the grid. Its single most useful
output is a physical reason why curtailment is a *network* problem rather than a
*weather* problem.

**Layout.** `data/` SEAI farm list + cached ERA5 pulls · `scripts/` the pipeline · `script-output/` results

---

## The result

**Irish wind barely decorrelates across the island.**

| Distance apart | Mean correlation |
|---|---|
| 0–10 km | 0.985 |
| 10–25 km | 0.949 |
| 25–50 km | 0.898 |
| 50–100 km | 0.825 |
| 100–150 km | 0.746 |
| 150–200 km | 0.656 |
| 200–400 km | 0.550 |

Fitting `corr(d) = exp(-d/L)` gives a **decorrelation length L ≈ 460 km** —
longer than Ireland's longest dimension (~450 km). Correlation never decays away
within the country.

**Winter is worse.** Re-running for January 2025 gives **L ≈ 599 km**, with
farms 200–400 km apart correlating at **0.66** rather than 0.55. So geographic
spread helps *least* in the season when wind output, and curtailment, are
highest. That is the sharper version of the result.

**Why it matters.** Atlantic synoptic weather systems are larger than Ireland, so
when it is windy it is windy nearly everywhere at once. Curtailment events are
therefore **national and near-simultaneous**, and you **cannot** solve them by
spreading wind farms further apart. That is why the binding constraints are
network topology and minimum conventional generation — not weather diversity.

---

## The model is validated against observation

`scripts/validate_against_eirgrid.py` is the only place the model meets reality. EirGrid
publishes **IE Wind Availability** at 15-minute resolution: the metered figure for
how much wind *could* have been produced, before any dispatch-down. That is
exactly the quantity our pipeline estimates, so the two compare directly.

Over **5,087 hourly points**, January to July 2026:

| | Modelled | EirGrid measured |
|---|---|---|
| Mean output | 1,534 MW | 1,595 MW |
| Peak output | 4,304 MW | 4,340 MW |
| Capacity factor | 0.356 | 0.371 |

**r = 0.984 (r² = 0.968), bias −3.8%, RMSE 253 MW (5.9% of fleet capacity).**

Availability, not generation — generation is availability minus curtailment, and
the model knows nothing about curtailment. So this tests the weather-to-power
physics alone, which is exactly what it should test.

The small negative bias is expected and explained: the SEAI farm list is from
June 2022 and misses capacity connected since, which also produces the visible
ceiling at 4,304 MW in the scatter plot.

---

## Three caveats — state these on any slide

1. **ERA5 is a reanalysis, not a forecast.** Using it to "predict" is
   hindcasting. If you need a genuine forecast, Open-Meteo's `/v1/forecast`
   endpoint works for Irish coordinates (verified 5 Sep 2026, no API key).
2. **The ERA5 grid is ~0.25° (~28 km).** Farms closer than that share a grid cell
   and show correlation ≈ 1.0 as an artefact, not physics. The fit therefore uses
   only pairs more than 30 km apart.
3. **The power curve is generic**, not the real turbine at each site. Per-turbine
   curves are not public. Output is indicative.

A fourth: each figure covers **one month**. July 2025 matches the network
model's time series; January 2025 is the winter comparison. Neither is an annual
figure — quote the season with the number.

---

## Files, most important first

### 1. [scripts/wind_correlation.py](scripts/wind_correlation.py) — the analysis
Computes great-circle distance between every pair of farms, correlates their wind
series, and fits the exponential decay. Produces the table above.

### 2. [scripts/wind_power.py](scripts/wind_power.py) — wind speed to megawatts
Fetches hourly 100 m wind speed at each farm from Open-Meteo's ERA5 archive
(cached, so it downloads once), then converts to power.

The power curve is the physics:

| Wind speed | Output |
|---|---|
| below 3 m/s (cut-in) | 0 — the turbine doesn't turn |
| 3 to 12 m/s | ramps as **v³** (P = ½ρA·C_p·v³), normalised to rated |
| 12 to 25 m/s | capped at rated capacity |
| above 25 m/s (cut-out) | 0 — it shuts down to protect itself |

It also provides `shear()` for power-law extrapolation to a different hub height
(α ≈ 0.14 open terrain, 0.11 offshore, 0.20 complex terrain). ERA5 already gives
100 m, so this is only needed where hub height differs materially.

**Sanity check:** fleet mean capacity factor comes out at **0.219** for July 2025,
against a published **24%** annual figure. July is the low-wind month, so this is
the right answer and the pipeline is behaving.

### 3. [scripts/validate_against_eirgrid.py](scripts/validate_against_eirgrid.py) — the reality check
Compares the modelled fleet output against EirGrid's measured availability, hour
by hour, over Jan–Jul 2026. Writes [script-output/model-vs-eirgrid-hourly-2026.csv](script-output/model-vs-eirgrid-hourly-2026.csv).
Results above.

### 4. [scripts/wind_forecast.py](scripts/wind_forecast.py) — a genuine forecast
Everything else here uses ERA5 reanalysis, which reconstructs what the weather
*was*. This uses Open-Meteo's forecast endpoint, which is an actual numerical
weather prediction, with the same farm list and the same power curve so the two
are directly comparable.

Writes [script-output/wind-forecast-7day.csv](script-output/wind-forecast-7day.csv): fleet MW per hour, 7 days ahead.
Run on 5 September 2026 it covered **the hackathon week itself** — mean 1,842 MW
(CF 0.428), peaking at 4,284 MW, with 26% of hours above 60% of fleet capacity.

### 5. [scripts/farm_locations.py](scripts/farm_locations.py) — coordinates
Reprojects SEAI's 6-digit Irish National Grid eastings/northings (**EPSG:29903**,
TM75 — *not* ITM) to WGS84 lat/lon. Produces **313 farms, 4,304 MW** total
maximum export capacity, all inside an island bounding box.

Note it normalises whitespace in farm names: **21 names in the SEAI file contain
embedded newlines** (e.g. `Ballybane (Glanta Commons) Wind\nFarm`), which will
silently corrupt any newline-delimited join.

### 6. Data files

| File | What it is |
|---|---|
| [data/WindFarmsConnectedJune2022.csv](data/WindFarmsConnectedJune2022.csv) | Source: 313 connected farms, capacity, county, **nearest 110 kV node**, grid coordinates |
| [script-output/wind-farms-with-coordinates.csv](script-output/wind-farms-with-coordinates.csv) | Generated: the same farms with lat/lon added |
| [data/era5_wind_july2025.json](data/era5_wind_july2025.json) | Cached API pull: hourly 100 m wind, 313 farms × 744 hours |
| [script-output/wind-speed-100m-2025-07.npy](script-output/wind-speed-100m-2025-07.npy) | Generated: speed matrix, farms × hours (July 2025) |
| [script-output/wind-power-mw-2025-07.npy](script-output/wind-power-mw-2025-07.npy) | Generated: power matrix, MW per farm per hour |
| `script-output/wind-speed-100m-2025-01.npy`, `script-output/wind-power-mw-2025-01.npy` | The same two matrices for January 2025, the winter comparison |
| `data/era5_wind_2025-01-01_2025-01-31.json` | Cached API pull for the January run |
| [script-output/wind-forecast-7day.csv](script-output/wind-forecast-7day.csv) | Generated: 7-day fleet output forecast |
| [script-output/model-vs-eirgrid-hourly-2026.csv](script-output/model-vs-eirgrid-hourly-2026.csv) | Generated: modelled vs EirGrid-measured, 5,087 hours |
| `data/era5_wind_2026-01-01_2026-07-31.json` | Cached API pull for the validation run |
| [data](data) | EirGrid's contracted (not yet connected) wind farms, Nov 2025 |
| [script-output/wind-farm-row-order.csv](script-output/wind-farm-row-order.csv) | Generated: row order for the two `.npy` matrices |

`F110kV_Node_Name` in the SEAI file is the **join key to the network** — it links
each farm to a transmission node, and therefore to a constraint group.

---

## Running it

In order; each depends on the last. All run from any working directory.

```bash
python 04-meteorology/scripts/farm_locations.py                       # coordinates
python 04-meteorology/scripts/wind_power.py                           # July 2025
python 04-meteorology/scripts/wind_power.py 2025-01-01 2025-01-31     # January 2025
python 04-meteorology/scripts/wind_correlation.py                     # summer
python 04-meteorology/scripts/wind_correlation.py _2025-01            # winter
python 04-meteorology/scripts/wind_forecast.py                        # 7 days ahead
python 04-meteorology/scripts/validate_against_eirgrid.py             # reality check
```

`scripts/wind_power.py` caches each period's API pull, so a repeat run costs nothing.

---

## References

| File | Source | Licence | Retrieved |
|---|---|---|---|
| `data/WindFarmsConnectedJune2022.csv` | SEAI, *Wind Farms in Ireland* (built from the EirGrid and ESB Networks connected-generator lists). <https://seaiopendata.blob.core.windows.net/wind/WindFarmsConnectedJune2022.csv> · dataset page <https://data.gov.ie/dataset/wind-farms-in-ireland> | **CC BY 4.0** | 5 Sep 2026 |
| `data/era5_wind_july2025.json` | Open-Meteo Historical Weather API (ERA5 reanalysis), <https://archive-api.open-meteo.com/v1/archive> — 100 m wind speed, 2025-07-01 to 2025-07-31 | **CC BY 4.0**, no API key | 5 Sep 2026 |
| `script-output/wind-farms-with-coordinates.csv`, `wind_speed_100m*.npy`, `wind_power_mw*.npy`, `script-output/wind-farm-row-order.csv`, `script-output/wind-forecast-7day.csv` | **Generated** by the scripts in this folder | Derived | 5 Sep 2026 |
| `reference/TSO-Contracted-Wind-Report-2025-11-28.pdf` | EirGrid, *Contracted TSO Wind Farms*, correct as of 28 Nov 2025. Node, capacity and signed date for farms not yet connected | Free | 5 Sep 2026 |
| `scripts/farm_locations.py`, `scripts/wind_power.py`, `scripts/wind_correlation.py`, `scripts/wind_forecast.py`, `scripts/validate_against_eirgrid.py` | Written for this project | — | 5 Sep 2026 |
| `script-output/model-vs-eirgrid-hourly-2026.csv` | **Generated**: our model against EirGrid's measured IE Wind Availability from [../02-curtailment/script-output/system-state-15min-2026.csv](../02-curtailment/script-output/system-state-15min-2026.csv) | Derived | 5 Sep 2026 |

**Underlying reanalysis:** ERA5, produced by the European Centre for
Medium-Range Weather Forecasts (ECMWF) and distributed via the Copernicus Climate
Change Service. Open-Meteo redistributes it under CC BY 4.0.

**Coordinate reference systems:** source EPSG:29903 (TM75 / Irish Grid),
output EPSG:4326 (WGS84). Transformed with `pyproj` 3.7.2.

**Alternatives checked and working, 5 September 2026:**
- Open-Meteo forecast API — <https://api.open-meteo.com/v1/forecast> (a genuine
  forecast, unlike the archive)
- ECMWF open data — <https://data.ecmwf.int/forecasts/> (HTTP 200)

**Known public gap:** there is no open day-ahead *SNSP* feed for Ireland. A
*wind* forecast is available (used by `scripts/wind_forecast.py`); turning that into an
SNSP forecast would need a demand forecast too, and is a build, not a download.
