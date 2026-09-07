# Data Scope Audit

**Do we have everything we need?** Checked 5 September 2026, every URL fetched live.

**Short answer: yes for the core project, with three real gaps that no amount of
searching will close because the data is not published.**

---

## What we hold

| Layer | Have it? | Source |
|---|---|---|
| Transmission network (buses, lines, impedances, ratings) | ✅ | Nayer/Zenodo, 446 buses |
| Constraint group definitions | ✅ | EirGrid WDT PDF, parsed to CSV |
| Farm → constraint group mapping | ✅ | Model `prorata_groups`, 294 generators |
| MUON constraint structure | ✅ | Model `MUON_group`, 38 synchronous units |
| Dispatch-down by reason code, monthly | ✅ | EirGrid DD Summary, 2016–2026 |
| System state at 15-min (demand, wind, SNSP, interconnectors) | ✅ | EirGrid Qtr-Hourly, Jan–Jul 2026 |
| Wind farm locations + capacity | ✅ | SEAI, 313 farms |
| Contracted (future) wind farms | ✅ | EirGrid TSO Contracted Wind Report, Nov 2025 |
| Wind resource, historical | ✅ | ERA5 via Open-Meteo, any period |
| Wind forecast | ✅ | Open-Meteo forecast API |
| Half-hourly simulation inputs | ✅ | Model `ts_*` sheets, July 2025 |

**That is enough to build all three project stages.** Nothing below blocks you.

---

## The three real gaps

These are not findable. They are not published anywhere, by anyone.

### 1. Per-farm dispatch-down volumes
EirGrid sends each operator *their own* curtailment figures and publishes only
aggregates. So you can validate a constraint grouping at **station level**, never
at farm level, and any per-farm euro figure is modelled, not measured.

### 2. Which specific constraint was binding at a given moment
The published data tells you *how much* was dispatched down and *which category*
(constraint / curtailment / MUON / SNSP). It never says *which named group* bound
at 14:30 on a Tuesday. This is the gap that makes a reconstruction interesting —
and the reason you cannot fully check one.

### 3. Real turbine power curves per site
Not public. Every wind-to-power conversion here uses a generic IEC-style curve.
Levels are indicative; the shape of the profile is the trustworthy part.

**A fourth, softer gap:** no open day-ahead SNSP forecast. Open-Meteo gives a wind
forecast, and EirGrid publishes historical SNSP, so *predicting* SNSP is a model
you could build — but it is a build, not a download.

---

## Worth collecting if a specific angle needs it

Ranked by value. All verified reachable today; none are collected yet because
nothing currently planned requires them.

| # | Source | Why you would want it | Cost |
|---|---|---|---|
| 1 | **SEMOpx day-ahead prices** (`sem-o.com/market-data`) | Curtailment correlates with near-zero and negative prices. Turns "MWh wasted" into "€ wasted" with a market price rather than an assumed one | Low |
| 2 | **ESB Networks capacity heatmap** | Distribution-level headroom per substation. Only matters for a siting angle | Low |
| 3 | **SEAI wind atlas rasters** (100 m, EPSG:3857) | Long-run mean wind speed as a map layer. ERA5 already covers time series, so this is presentation value | Low |
| 4 | **TYTFS study files** (PSS/E format) | EirGrid's own power-flow cases. A cross-check on the Nayer model's impedances | High — proprietary format |
| 5 | **Smart Grid Dashboard API** | Live data during the hackathon week. Note the endpoint needs `datefrom`/`dateto`; a bare query returns HTTP 400 | Medium |
| 6 | **Met Éireann station observations** | Ground truth to validate ERA5 at ~25 points | Medium |
| 7 | **ENTSO-E Transparency Platform** | EU-wide cross-check. **Dropped** — token takes days and duplicates EirGrid data we already hold | Blocked |

---

## Things that look like data and are not

Checked, and not worth your time:

- **ESB Networks CAD network geometry** — FOI/request-only, will not clear in a week.
- **Wind Energy Ireland project database** — the free version is a map, not a
  dataset; the downloadable database is a paid market report.
- **Per-farm SCADA or metering** — commercially sensitive, and there is live CJEU
  litigation over redispatch compensation making holders more cautious, not less.
- **OpenInfraMap bulk country export** — the polished export is a paid product.
  Overpass Turbo gives the same OSM data free if you ever need line geometry.

---

## One correction to the existing briefings

The briefing documents list Ireland's interconnectors as EWIC (500 MW, 2012),
Moyle, Celtic (Q4 2028) and North–South (Oct 2031). **They omit Greenlink.**

The quarter-hourly system data carries a `Greenlink I/C` column that is active in
**89% of periods**, mean **+313 MW**, range −296 to +521 MW. It is operational and
carrying real power throughout 2026. Any interconnector discussion that lists only
EWIC and Moyle as live is out of date.

*(Greenlink is a 500 MW HVDC link between Great Island, Co. Wexford and Pembroke,
Wales. Its capacity here is inferred from the observed flow range in EirGrid's own
data, not from a datasheet — state it as observed, or check a primary source
before quoting a rating.)*

---

## References

| Checked | Result |
|---|---|
| EirGrid annual curtailment reports 2023, 2024 | HTTP 200 — **downloaded** to [../02-curtailment/data/archive](../02-curtailment/data/archive) |
| EirGrid TSO Contracted Wind Report, 28 Nov 2025 | HTTP 200 — **downloaded** to [../04-meteorology/data](../04-meteorology/data) |
| EirGrid connected & contracted generators page | HTTP 200 — links to the two PDFs above, no spreadsheet offered |
| SEMO market data | HTTP 200 |
| SEAI wind speed rasters (100 m) | HTTP 200 |
| ESB Networks capacity heatmap | HTTP 200 |
| Open-Meteo forecast API | HTTP 200 |
| Smart Grid Dashboard API | HTTP 400 on a bare query — needs date parameters |

All checks performed 5 September 2026. Version-numbered EirGrid files
(`V21`, `V28`, `V7`) are incremented on republication; re-check the hub page
before quoting figures in the presentation.
