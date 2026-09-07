# 07 — Figures

Every chart in the project, built from the data in folders 02, 03, 04 and 08.

```bash
python 07-figures/scripts/make_figures.py
```

Regenerates all fourteen PNGs. Nothing here is hand-drawn, so any figure can be
rebuilt after the underlying data changes.

**Layout.** `scripts/` one script · `charts/` twelve PNGs

---

## The figures

Ordered by how useful they are for the Friday presentation.

The **rank** column is presentation priority, not the filename. Filenames keep
their original numbering so links stay stable.

| Rank | Figure | What it says |
|---|---|---|
| **1** | [charts/01-dispatch-down-trend.png](charts/01-dispatch-down-trend.png) | Dispatch-down has risen from ~3% (2016) to 13–24% (2026). **The problem is getting worse, fast** |
| **2** | [charts/03-curtailment-causes.png](charts/03-curtailment-causes.png) | Minimum-units-online dominates curtailment; the SNSP cap is a small share. **The headline metric is not the binding one** |
| **3** | [charts/13-weather-vs-effectiveness.png](charts/13-weather-vs-effectiveness.png) | The same groups tested two ways: weather explains nothing, effectiveness explains almost everything. **The project's core result** |
| **4** | [charts/14-clustering-options.png](charts/14-clustering-options.png) | Three clustering methods scored against the real groups. F1 finds groups; omega says the overlap structure is not yet captured |
| **5** | [charts/11-model-vs-eirgrid-measured.png](charts/11-model-vs-eirgrid-measured.png) | Our wind model against EirGrid's own measurements, r² = 0.968 over 5,087 hours. **The pipeline is validated, not assumed** |
| **6** | [charts/12-groups-vs-weather-test.png](charts/12-groups-vs-weather-test.png) | Constraint groups are no more wind-correlated than distance alone predicts. **They encode topology, not weather** |
| **7** | [charts/05-wind-correlation-by-distance.png](charts/05-wind-correlation-by-distance.png) | Wind stays correlated across the island, more so in winter. **Geographic spread cannot fix curtailment** |
| **8** | [charts/02-ireland-curtailment-vs-constraint.png](charts/02-ireland-curtailment-vs-constraint.png) | Local constraint overtook system-wide curtailment in Ireland in 2025 |
| **9** | [charts/10-wind-duration-curve.png](charts/10-wind-duration-curve.png) | Available wind against what the system took — the gap *is* the problem |
| **10** | [charts/08-constraint-groups-by-region.png](charts/08-constraint-groups-by-region.png) | Constraint groups cluster in the west and south west |
| **11** | [charts/07-wind-farm-map.png](charts/07-wind-farm-map.png) | 313 farms, sized by capacity, showing which are matched to the network model |
| **12** | [charts/04-snsp-distribution.png](charts/04-snsp-distribution.png) | The system runs at 55% SNSP on average against a 75% ceiling |
| **13** | [charts/06-turbine-power-curve.png](charts/06-turbine-power-curve.png) | Why a small wind change is a large power change (v³) |
| **14** | [charts/09-wind-forecast-7day.png](charts/09-wind-forecast-7day.png) | Forecast wind for the hackathon week itself |

---

## Design rules applied

These are not stylistic preferences; each prevents a specific way charts mislead.

- **No dual axes anywhere.** Two y-scales on one chart is the most common
  charting error — it lets the author imply any correlation they like by
  choosing scales. Where two measures differ in scale they get two panels.
- **A validated colour palette.** Checked for colourblind separation (worst
  adjacent pair ΔE 9.1, target ≥8), lightness band, and chroma floor — computed,
  not eyeballed. Hues are assigned in fixed order and never cycled.
- **Colour never carries meaning alone.** Every multi-series chart has both a
  legend and direct labels, because three palette slots sit below 3:1 contrast on
  a light surface.
- **Sequential magnitude uses one hue**, light to dark — never a rainbow.
- **Recessive grid and axes**, thin marks, and labels only where they inform —
  never a number on every point.
- **Every figure carries its source and its caveat** in a footnote, so a chart
  lifted into a slide deck takes its provenance with it.

---

## Caveats that travel with the data

State these if the figure goes on a slide. Referenced by **filename**, not rank.

- **2026 is a partial year** (January–July) in `01`, `02`, `03`, `04`, `10`, `11`.
- **`03` is a share of *curtailment*, not of total dispatch-down.** Constraint is
  excluded. This distinction is the single easiest thing to get wrong.
- **`05`:** pairs under 30 km share an ERA5 grid cell (~28 km), so their
  correlation is partly an artefact of the weather model's resolution, not physics.
- **`05`, `06`, `09`, `10`, `11`** rest on a generic IEC-style power curve, not the
  real turbine at each site. Trust the shape, not the level.
- **`09` is a genuine forecast**, unlike everything else here, which uses ERA5
  reanalysis. Do not describe reanalysis as prediction.
- **`10`** sorts both curves independently, so it shows the volume gap between
  them, not paired hours.
- **`11`** compares *availability* (pre-curtailment), so it tests the
  weather-to-power model alone. The flat top at 4,304 MW is our fleet-capacity
  cap: the SEAI farm list is from 2022 and misses newer capacity.
- **`12`** uses the network model's `prorata_groups`, so it covers only the 12
  groups with four or more matched farms — not all 39.

---

## References

| Figure | Data source |
|---|---|
| 1, 2, 3 | [../02-curtailment/script-output/dispatch-down-by-reason-monthly.csv](../02-curtailment/script-output/dispatch-down-by-reason-monthly.csv) — extracted from EirGrid *DD Summary Report V21* |
| 4, 10 | [../02-curtailment/script-output/system-state-15min-2026.csv](../02-curtailment/script-output/system-state-15min-2026.csv) — extracted from EirGrid *System Data Qtr Hourly 2026 V7* |
| 5, 6 | [../04-meteorology/](../04-meteorology/) — ERA5 via Open-Meteo (CC BY 4.0), generic power curve |
| 7 | [../03-network/script-output/farm-to-constraint-group-map.csv](../03-network/script-output/farm-to-constraint-group-map.csv) — SEAI farm list (CC BY 4.0) joined to the Nayer network model (CC BY 4.0) |
| 8 | [../03-network/script-output/constraint-groups-to-stations.csv](../03-network/script-output/constraint-groups-to-stations.csv) — parsed from EirGrid *Wind Dispatch Tool Constraint Group Overview*, 1 Feb 2024 |
| 9 | [../04-meteorology/script-output/wind-forecast-7day.csv](../04-meteorology/script-output/wind-forecast-7day.csv) — Open-Meteo forecast API |
| 11 | [../04-meteorology/script-output/model-vs-eirgrid-hourly-2026.csv](../04-meteorology/script-output/model-vs-eirgrid-hourly-2026.csv) — our model against EirGrid's measured availability |
| 12 | [../08-analysis/script-output/groups-vs-weather-test.csv](../08-analysis/script-output/groups-vs-weather-test.csv) — group correlation against a distance-only null |
| 14 | [../08-analysis/script-output/clustering-options-scores.csv](../08-analysis/script-output/clustering-options-scores.csv) — three methods scored against the real groups |
| 13 | the weather test above, plus [../08-analysis/script-output/groups-vs-effectiveness-test.csv](../08-analysis/script-output/groups-vs-effectiveness-test.csv) — PTDF coherence against a random-farm null |

Palette: validated default categorical palette, light surface `#fcfcfb`.
Rendered with matplotlib at 150 dpi.
